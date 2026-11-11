import os
import csv
import json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def prep_pmse(input_path, output_path):
    print(f"Processing {input_path}...")
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    blocks_index = []
    # Clean and round coordinates to 6 decimals & build spatial index
    for feat in data.get('features', []):
        props = feat.get('properties', {})
        geom = feat.get('geometry', {})
        gtype = geom.get('type')
        rings = []
        if gtype == 'Polygon':
            geom['coordinates'] = [[[round(c, 6) for c in pt] for pt in ring] for ring in geom['coordinates']]
            if geom['coordinates']:
                rings.append(geom['coordinates'][0])
        elif gtype == 'MultiPolygon':
            geom['coordinates'] = [[[[round(c, 6) for c in pt] for pt in ring] for poly in geom['coordinates']] for ring in poly] if False else [
                [[[round(c, 6) for c in pt] for pt in ring] for ring in poly] for poly in geom['coordinates']
            ]
            for poly in geom['coordinates']:
                if poly:
                    rings.append(poly[0])

        for r in rings:
            lons = [pt[0] for pt in r]
            lats = [pt[1] for pt in r]
            blocks_index.append({
                'blok': str(props.get('blok', '')),
                'divisi': str(props.get('divisi', '')),
                'min_lon': min(lons),
                'max_lon': max(lons),
                'min_lat': min(lats),
                'max_lat': max(lats),
                'ring': r
            })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, separators=(',', ':'))
    print(f"Saved {output_path} ({os.path.getsize(output_path) / 1024:.1f} KB)")
    return blocks_index


def point_in_poly(lon, lat, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def dist_sq_to_segment(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return (px - x1) ** 2 + (py - y1) ** 2
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return (px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2


def match_block_and_divisi(lat, lon, blocks_index):
    if not blocks_index:
        return '', ''
    # 1. Exact point-in-polygon check
    for b in blocks_index:
        if b['min_lat'] <= lat <= b['max_lat'] and b['min_lon'] <= lon <= b['max_lon']:
            if point_in_poly(lon, lat, b['ring']):
                return b['blok'], b['divisi']

    # 2. Boundary road corridor fallback (~400m / 0.004 deg)
    best_d2 = 0.004 ** 2
    best_match = ('Luar Blok', 'LUAR BLOK')
    for b in blocks_index:
        if (b['min_lat'] - 0.004 <= lat <= b['max_lat'] + 0.004 and
                b['min_lon'] - 0.004 <= lon <= b['max_lon'] + 0.004):
            r = b['ring']
            for i in range(len(r) - 1):
                d2 = dist_sq_to_segment(lon, lat, r[i][0], r[i][1], r[i + 1][0], r[i + 1][1])
                if d2 < best_d2:
                    best_d2 = d2
                    best_match = (b['blok'], b['divisi'])
    return best_match


def safe_float(val, default=0.0):
    try:
        if val is None or val == '':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


def process_csv(csv_path, output_path, date_key, blocks_index):
    print(f"Processing {csv_path}...")
    groups = {}
    order = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            lat = safe_float(row.get('Latitude'))
            lon = safe_float(row.get('Longitude'))
            # Filter valid coordinates in Kalimantan Timur region
            if not (0.5 < lat < 5.0 and 110.0 < lon < 120.0):
                continue

            fname = row['Filename']
            if fname not in groups:
                groups[fname] = {
                    'first': row,
                    'coords': [],
                    'speeds': [],
                    'z_vals': [],
                    'y_vals': []
                }
                order.append(fname)

            g = groups[fname]
            g['coords'].append([round(lat, 6), round(lon, 6)])
            g['speeds'].append(round(safe_float(row.get('Speed')), 2))
            g['z_vals'].append(safe_float(row.get('Z')))
            g['y_vals'].append(safe_float(row.get('Y')))

    segments = []
    for fname in order:
        g = groups[fname]
        r0 = g['first']
        coords = g['coords']
        speeds = g['speeds']
        z_vals = g['z_vals']

        # Calculate vertical/longitudinal shock peak (Z is centered at 0, Y has 9.81 gravity)
        z_abs = [abs(z) for z in z_vals]
        z_peak = max(z_abs) if z_abs else 0.0

        avg_spd_raw = r0.get('AVG Speed', '')
        avg_spd = safe_float(avg_spd_raw, sum(speeds) / len(speeds) if speeds else 0.0)
        iri_val = safe_float(r0.get('IRI'), 0.0)
        dist_val = safe_float(r0.get('Aktual Distance'), 0.0)

        # Deduplicate consecutive identical GPS coordinates while preserving polyline shape
        dedup_coords = []
        for pt in coords:
            if not dedup_coords or dedup_coords[-1] != pt:
                dedup_coords.append(pt)
        if len(dedup_coords) == 1:
            dedup_coords.append(dedup_coords[0])

        # Midpoint for spatial block/division lookup
        mid_pt = dedup_coords[len(dedup_coords) // 2]
        blok, divisi = match_block_and_divisi(mid_pt[0], mid_pt[1], blocks_index)

        step_s = max(1, len(speeds) // 15)
        step_z = max(1, len(z_vals) // 15)

        segments.append({
            'file': fname,
            'date': date_key,
            'start': str(r0.get('Timestamp Start', '')),
            'end': str(r0.get('Timestamp End', '')),
            'iri': round(iri_val, 2),
            'avg_speed': round(avg_spd, 1),
            'max_speed': round(max(speeds), 1) if speeds else 0.0,
            'dist': round(dist_val, 1),
            'status': str(r0.get('Status', '')),
            'color': str(r0.get('Color', '')).upper(),
            'blok': blok,
            'divisi': divisi,
            'coords': dedup_coords,
            'point_count': len(coords),
            'z_peak': round(z_peak, 2),
            'spark_speed': speeds[::step_s],
            'spark_z': [round(v, 2) for v in z_vals[::step_z]]
        })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(segments, f, separators=(',', ':'))

    print(f"Saved {output_path} with {len(segments)} segments ({os.path.getsize(output_path) / 1024:.1f} KB)")
    return segments


def compute_stats(runs_dict, output_path):
    def stats_for_list(segs, name):
        if not segs:
            return {}
        total_dist_km = sum(s['dist'] for s in segs) / 1000.0
        pos_speeds = [s['avg_speed'] for s in segs if s['avg_speed'] > 0]
        avg_speed = sum(pos_speeds) / len(pos_speeds) if pos_speeds else 0.0
        max_speed = max((s['max_speed'] for s in segs), default=0.0)
        pos_iris = [s['iri'] for s in segs if s['iri'] > 0]
        avg_iri = sum(pos_iris) / len(pos_iris) if pos_iris else 0.0

        status_counts = {}
        color_counts = {}
        for s in segs:
            st = s['status']
            status_counts[st] = status_counts.get(st, 0) + 1
            c = s['color']
            color_counts[c] = color_counts.get(c, 0) + 1

        return {
            'name': name,
            'total_segments': len(segs),
            'total_distance_km': round(total_dist_km, 2),
            'avg_speed': round(float(avg_speed), 1),
            'max_speed': round(float(max_speed), 1),
            'avg_iri': round(float(avg_iri), 2),
            'status_counts': status_counts,
            'color_counts': color_counts,
            'severe_damage_count': status_counts.get('Rusak Berat (2)', 0)
        }

    all_segs = []
    summary = {}
    labels = {
        '20261103': '03 Nov 2026',
        '20261104': '04 Nov 2026',
        '20261105': '05 Nov 2026',
        '20261106': '06 Nov 2026'
    }
    for dt, segs in runs_dict.items():
        summary[f'run_{dt}'] = stats_for_list(segs, labels.get(dt, dt))
        all_segs.extend(segs)

    summary['combined'] = stats_for_list(all_segs, 'All Surveys (03-06 Nov 2026)')

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(f"Saved {output_path}")


if __name__ == '__main__':
    web_data_dir = os.path.join(BASE_DIR, 'web', 'data')
    os.makedirs(web_data_dir, exist_ok=True)

    blocks_idx = prep_pmse(
        os.path.join(BASE_DIR, 'PMSE.json'),
        os.path.join(web_data_dir, 'pmse_blocks.json')
    )

    datasets = {
        '20261103': 'ROSE/Accelerometer Data - 23000988_20261103-20261103 A27/Accelerometer Data.csv',
        '20261104': 'ROSE/Accelerometer Data - 23000988_20261104-20261104 A27/Accelerometer Data.csv',
        '20261105': 'ROSE/Accelerometer Data - 23000988_20261105-20261105/Accelerometer Data.csv',
        '20261106': 'ROSE/Accelerometer Data - 23000988_20261106-20261106/Accelerometer Data.csv',
    }

    runs = {}
    for dt, rel_csv in datasets.items():
        full_csv = os.path.join(BASE_DIR, rel_csv)
        if os.path.exists(full_csv):
            runs[dt] = process_csv(
                full_csv,
                os.path.join(web_data_dir, f'data_{dt}.json'),
                dt,
                blocks_idx
            )

    compute_stats(runs, os.path.join(web_data_dir, 'summary_stats.json'))
    print("Data preparation complete!")
