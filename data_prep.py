import os
import csv
import json
import math
from shapely.geometry import shape, mapping, Point, LineString, Polygon, MultiPolygon
from shapely.validation import make_valid
from shapely.ops import unary_union, linemerge
from shapely.strtree import STRtree

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Local metric projection constants centered on PMSE Estate (~1.015 N, 116.945 E)
LON0, LAT0 = 116.945, 1.015
SX, SY = 111302.0, 110574.0


def pt_to_m(pt):
    return ((pt[0] - LON0) * SX, (pt[1] - LAT0) * SY)


def pt_to_deg(pt):
    return [round(LON0 + pt[0] / SX, 6), round(LAT0 + pt[1] / SY, 6)]


def geom_to_m(geom):
    if geom.geom_type == 'Polygon':
        ext = [pt_to_m(p) for p in geom.exterior.coords]
        ints = [[pt_to_m(p) for p in r.coords] for r in geom.interiors]
        return make_valid(Polygon(ext, ints))
    elif geom.geom_type == 'MultiPolygon':
        return make_valid(MultiPolygon([geom_to_m(p) for p in geom.geoms]))
    return geom


def poly_m_to_geojson_coords(poly):
    ext = [pt_to_deg(p) for p in poly.exterior.coords]
    ints = [[pt_to_deg(p) for p in r.coords] for r in poly.interiors]
    return [ext] + ints


def geom_m_to_geojson(geom):
    if geom.geom_type == 'Polygon':
        return {
            'type': 'Polygon',
            'coordinates': poly_m_to_geojson_coords(geom)
        }
    elif geom.geom_type == 'MultiPolygon':
        polys = [p for p in geom.geoms if not p.is_empty and p.area > 1.0]
        if len(polys) == 1:
            return {
                'type': 'Polygon',
                'coordinates': poly_m_to_geojson_coords(polys[0])
            }
        return {
            'type': 'MultiPolygon',
            'coordinates': [poly_m_to_geojson_coords(p) for p in polys]
        }
    return mapping(geom)


def angle_diff_deg(a1_rad, a2_rad):
    diff = abs(math.degrees(a2_rad - a1_rad)) % 360.0
    return 360.0 - diff if diff > 180.0 else diff


def extend_line(pts, ext_m=12.0):
    if len(pts) < 2:
        return pts
    res = list(pts)
    dx0, dy0 = res[1][0] - res[0][0], res[1][1] - res[0][1]
    L0 = math.hypot(dx0, dy0)
    if L0 > 1e-6:
        res[0] = (res[0][0] - dx0 / L0 * ext_m, res[0][1] - dy0 / L0 * ext_m)
    dx1, dy1 = res[-1][0] - res[-2][0], res[-1][1] - res[-2][1]
    L1 = math.hypot(dx1, dy1)
    if L1 > 1e-6:
        res[-1] = (res[-1][0] + dx1 / L1 * ext_m, res[-1][1] + dy1 / L1 * ext_m)
    return res


def extract_lines(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == 'LineString':
        return [geom]
    lines = []
    if hasattr(geom, 'geoms'):
        for g in geom.geoms:
            if g.geom_type == 'LineString':
                lines.append(g)
            elif g.geom_type == 'MultiLineString':
                lines.extend(g.geoms)
    if not lines:
        return []
    merged = linemerge(lines)
    if merged.geom_type == 'LineString':
        return [merged]
    elif hasattr(merged, 'geoms'):
        return [g for g in merged.geoms if g.geom_type == 'LineString']
    return []


def split_into_chains(ls, is_closed=False):
    coords = list(ls.coords)
    clean_pts = [coords[0]]
    for pt in coords[1:]:
        if math.hypot(pt[0] - clean_pts[-1][0], pt[1] - clean_pts[-1][1]) >= 0.1:
            clean_pts.append(pt)
    if len(clean_pts) < 2:
        return []

    chains = []
    for i in range(len(clean_pts) - 1):
        p1, p2 = clean_pts[i], clean_pts[i + 1]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        L = math.hypot(dx, dy)
        if L < 0.1:
            continue
        ang_rad = math.atan2(dy, dx)
        if chains:
            prev = chains[-1]
            step_turn = angle_diff_deg(prev['last_ang'], ang_rad)
            mean_ang = math.atan2(prev['dy_sum'], prev['dx_sum'])
            cum_turn = angle_diff_deg(mean_ang, ang_rad)
            if step_turn <= 38.0 and cum_turn <= 50.0:
                prev['pts'].append(p2)
                prev['len'] += L
                prev['dx_sum'] += dx
                prev['dy_sum'] += dy
                prev['last_ang'] = ang_rad
                continue
            else:
                prev['end_sharp'] = (step_turn > 38.0)

        start_sharp = chains[-1]['end_sharp'] if chains else (not is_closed)
        chains.append({
            'pts': [p1, p2],
            'len': L,
            'dx_sum': dx,
            'dy_sum': dy,
            'first_ang': ang_rad,
            'last_ang': ang_rad,
            'start_sharp': start_sharp,
            'end_sharp': (not is_closed)
        })

    if is_closed and len(chains) > 1:
        c0, cl = chains[0], chains[-1]
        step_turn = angle_diff_deg(cl['last_ang'], c0['first_ang'])
        mean_ang0 = math.atan2(c0['dy_sum'], c0['dx_sum'])
        mean_angl = math.atan2(cl['dy_sum'], cl['dx_sum'])
        if step_turn <= 38.0 and angle_diff_deg(mean_angl, mean_ang0) <= 50.0:
            chains.pop(0)
            cl['pts'].extend(c0['pts'][1:])
            cl['len'] += c0['len']
            cl['dx_sum'] += c0['dx_sum']
            cl['dy_sum'] += c0['dy_sum']
            cl['last_ang'] = c0['last_ang']
            cl['end_sharp'] = c0['end_sharp']
        else:
            sharp_wrap = (step_turn > 38.0)
            cl['end_sharp'] = sharp_wrap
            c0['start_sharp'] = sharp_wrap

    return chains


def classify_chain(c):
    p_start, p_end = c['pts'][0], c['pts'][-1]
    cdx, cdy = p_end[0] - p_start[0], p_end[1] - p_start[1]
    chord = math.hypot(cdx, cdy)
    ang = abs(math.degrees(math.atan2(cdy, cdx)))
    straight = (chord / c['len']) >= 0.90 if c['len'] > 0 else False
    if straight and (ang <= 15.0 or ang >= 165.0):
        return 'Jalan MR', 9.0
    elif straight and (75.0 <= ang <= 105.0):
        return 'Jalan CR', 7.0
    else:
        return 'Jalan Kontur', 7.0


# Pre-traced centerlines ([lon, lat]) for the 5 main Jalan Raya / Jalan Akses corridors outside PMSE & JLYE
DEFAULT_HIGHWAY_CORRIDORS = [
    {
        'estate': 'LUAR KEBUN',
        'divisi': 'LUAR BLOK',
        'blok': 'Poros PMSE–JLYE',
        'antar_blok': 'Poros Utama PMSE – JLYE',
        'keterangan': 'Jalan Raya',
        'lebar_m': 12,
        'centerline': [
            [116.942555, 0.997032], [116.943238, 0.997087], [116.943453, 0.99928],
            [116.943567, 1.001478], [116.943546, 1.003424], [116.942998, 1.007656],
            [116.94306, 1.008171], [116.943712, 1.010288], [116.943829, 1.011099],
            [116.943702, 1.011785], [116.943425, 1.01244], [116.942302, 1.013936],
            [116.942148, 1.014719], [116.942148, 1.015206], [116.942257, 1.015266]
        ]
    },
    {
        'estate': 'LUAR KEBUN',
        'divisi': 'LUAR BLOK',
        'blok': 'Lingkar Barat JLYE',
        'antar_blok': 'Lingkar Barat JLYE',
        'keterangan': 'Jalan Raya',
        'lebar_m': 12,
        'centerline': [
            [116.9487, 0.987853], [116.947514, 0.987648], [116.947194, 0.987745],
            [116.947018, 0.988018], [116.946681, 0.989424], [116.945672, 0.990173],
            [116.945003, 0.99165], [116.944688, 0.991832], [116.943612, 0.991864],
            [116.943291, 0.991945], [116.942487, 0.992782], [116.942336, 0.993293],
            [116.942455, 0.993569], [116.942885, 0.994048], [116.942982, 0.994281],
            [116.943215, 0.996871], [116.943112, 0.997005], [116.942537, 0.996989]
        ]
    },
    {
        'estate': 'LUAR KEBUN',
        'divisi': 'LUAR BLOK',
        'blok': 'Lingkar Selatan JLYE',
        'antar_blok': 'Lingkar Selatan JLYE',
        'keterangan': 'Jalan Raya',
        'lebar_m': 12,
        'centerline': [
            [116.94872, 0.987855], [116.94892, 0.987897], [116.949518, 0.988436],
            [116.949826, 0.988513], [116.951469, 0.987973], [116.952573, 0.988226],
            [116.953524, 0.987955], [116.953976, 0.988037], [116.954192, 0.988244],
            [116.954491, 0.988802], [116.954962, 0.990113], [116.955696, 0.990761],
            [116.955964, 0.9917], [116.956216, 0.991864], [116.956619, 0.991822]
        ]
    },
    {
        'estate': 'PMSE',
        'divisi': 'LUAR BLOK',
        'blok': 'Poros Tengah Barat',
        'antar_blok': 'Poros Emplasemen PMSE (Barat)',
        'keterangan': 'Jalan Raya',
        'lebar_m': 10,
        'centerline': [
            [116.937433, 1.01531], [116.942257, 1.015266]
        ]
    },
    {
        'estate': 'PMSE',
        'divisi': 'LUAR BLOK',
        'blok': 'Poros Tengah Timur',
        'antar_blok': 'Poros Emplasemen PMSE (Timur)',
        'keterangan': 'Jalan Raya',
        'lebar_m': 10,
        'centerline': [
            [116.942257, 1.015266], [116.948297, 1.015174]
        ]
    }
]


def prep_pmse(input_paths, output_path, roads_output_path=None, combined_output_path=None):
    if isinstance(input_paths, str):
        input_paths = [input_paths]

    all_raw_features = []
    crs_info = None
    for ipath in input_paths:
        if not os.path.exists(ipath):
            continue
        print(f"Processing {ipath} and generating road corridor polygons...")
        with open(ipath, 'r', encoding='utf-8') as f:
            d = json.load(f)
            if not crs_info and d.get('crs'):
                crs_info = d.get('crs')
            all_raw_features.extend(d.get('features', []))

    named_feats = [f for f in all_raw_features if f.get('properties', {}).get('blok') != '-']
    unnamed_feats = [f for f in all_raw_features if f.get('properties', {}).get('blok') == '-']

    geoms_m = [geom_to_m(shape(f['geometry'])).buffer(0) for f in named_feats]
    bloks = [str(f['properties'].get('blok', '')) for f in named_feats]
    divisis = [str(f['properties'].get('divisi', '')) for f in named_feats]
    estates = [str(f['properties'].get('estate', 'PMSE')) for f in named_feats]
    tree = STRtree(geoms_m)

    block_cuts = [[] for _ in range(len(named_feats))]
    near_shared_masks = [[] for _ in range(len(named_feats))]
    road_candidates = []

    # 1. Shared & near-shared boundaries between pairs of named blocks (i < j)
    for i in range(len(named_feats)):
        for j in tree.query(geoms_m[i]):
            if j <= i:
                continue
            inter = geoms_m[i].boundary.intersection(geoms_m[j].boundary)
            inter_lines = extract_lines(inter)
            inter_len = sum(l.length for l in inter_lines)

            # Handle cross-estate or slightly gapped boundaries (< 4.5 m) as a single shared road
            is_near_shared = False
            if geoms_m[i].distance(geoms_m[j]) < 4.5:
                buf_j = geoms_m[j].boundary.buffer(4.0)
                near_inter = geoms_m[i].boundary.intersection(buf_j)
                near_lines = extract_lines(near_inter)
                near_len = sum(l.length for l in near_lines)
                if near_len > inter_len + 5.0:
                    inter_lines = near_lines
                    is_near_shared = True
                    near_shared_masks[i].append(buf_j)
                    near_shared_masks[j].append(geoms_m[i].boundary.buffer(4.0))

            for ls in inter_lines:
                if ls.length < 1.0:
                    continue
                if not ls.is_ring and ls.length > 15.0:
                    ls = ls.simplify(3.0 if is_near_shared else 2.0, preserve_topology=False)
                chains = split_into_chains(ls, is_closed=ls.is_ring)
                for c in chains:
                    if c['len'] <= 12.5 and (ls.length <= 18.0 or c['start_sharp'] or c['end_sharp']):
                        continue
                    rtype, w = classify_chain(c)
                    line_obj = LineString(c['pts'])
                    mid_pt = line_obj.interpolate(0.5, normalized=True)
                    p_a = line_obj.interpolate(max(0.0, 0.5 - 0.05), normalized=True)
                    p_b = line_obj.interpolate(min(1.0, 0.5 + 0.05), normalized=True)
                    tdx, tdy = p_b.x - p_a.x, p_b.y - p_a.y
                    tL = math.hypot(tdx, tdy) or 1.0
                    nx, ny = -tdy / tL, tdx / tL
                    pt_left = Point(mid_pt.x + 2.0 * nx, mid_pt.y + 2.0 * ny)
                    i_is_left = geoms_m[i].distance(pt_left) < geoms_m[j].distance(pt_left)
                    inx = nx if i_is_left else -nx
                    iny = ny if i_is_left else -ny

                    if rtype == 'Jalan MR':
                        owner = i if iny < 0 else j
                    elif rtype == 'Jalan CR':
                        owner = i if inx < 0 else j
                    else:
                        owner = i if (iny + inx) < 0 else j

                    other = j if owner == i else i
                    ext_ls = LineString(extend_line(c['pts'], 12.0))
                    buf = ext_ls.buffer(w, cap_style='flat', join_style='mitre', mitre_limit=3.0)
                    owner_poly = geoms_m[owner].buffer(2.0) if is_near_shared else geoms_m[owner]
                    strip = make_valid(owner_poly.intersection(buf))
                    block_cuts[owner].append(buf)
                    if not strip.is_empty and strip.area > 5.0:
                        road_candidates.append({
                            'owner_idx': owner,
                            'estate': estates[owner],
                            'divisi': divisis[owner],
                            'blok': bloks[owner],
                            'neighbor': bloks[other],
                            'rtype': rtype,
                            'width': int(w),
                            'len': round(c['len'], 1),
                            'pts_m': c['pts'],
                            'geom': strip
                        })

    # 2. Unshared outer boundaries of each named block
    for i in range(len(named_feats)):
        other_bounds = [geoms_m[j].boundary for j in tree.query(geoms_m[i]) if j != i]
        sub_geoms = other_bounds + near_shared_masks[i]
        outer = geoms_m[i].boundary.difference(unary_union(sub_geoms)) if sub_geoms else geoms_m[i].boundary
        for ls in extract_lines(outer):
            if ls.length <= 12.5:
                continue
            if not ls.is_ring and ls.length > 15.0:
                ls = ls.simplify(2.0, preserve_topology=False)
            chains = split_into_chains(ls, is_closed=ls.is_ring)
            for c in chains:
                if c['len'] <= 12.5:
                    continue
                rtype, w = classify_chain(c)
                ext_ls = LineString(extend_line(c['pts'], 12.0))
                buf = ext_ls.buffer(w, cap_style='flat', join_style='mitre', mitre_limit=3.0)
                strip = make_valid(geoms_m[i].intersection(buf))
                block_cuts[i].append(buf)
                if not strip.is_empty and strip.area > 5.0:
                    road_candidates.append({
                        'owner_idx': i,
                        'estate': estates[i],
                        'divisi': divisis[i],
                        'blok': bloks[i],
                        'neighbor': None,
                        'rtype': rtype,
                        'width': int(w),
                        'len': round(c['len'], 1),
                        'pts_m': c['pts'],
                        'geom': strip
                    })

    # 3. De-overlap road strips per owner block (Priority: Jalan MR > Jalan CR > Jalan Kontur)
    prio_map = {'Jalan MR': 0, 'Jalan CR': 1, 'Jalan Kontur': 2}
    road_candidates.sort(key=lambda r: (r['owner_idx'], prio_map[r['rtype']], -r['len']))
    used_per_block = [Polygon() for _ in range(len(named_feats))]
    road_geojson_features = []

    for r in road_candidates:
        oidx = r['owner_idx']
        clean_geom = make_valid(r['geom'].difference(used_per_block[oidx]))
        if clean_geom.geom_type == 'GeometryCollection':
            polys = [g for g in clean_geom.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
            clean_geom = unary_union(polys) if polys else Polygon()
        if not clean_geom.is_empty and clean_geom.area > 5.0:
            used_per_block[oidx] = unary_union([used_per_block[oidx], clean_geom])
            area_m2 = clean_geom.area
            ha = round(area_m2 / 10000.0, 4)
            panjang_m = round(area_m2 / r['width'], 1)
            antar_blok = f"{r['blok']} – {r['neighbor']}" if r['neighbor'] else r['blok']
            pts_m = list(r['pts_m'])
            dx_c = pts_m[-1][0] - pts_m[0][0]
            dy_c = pts_m[-1][1] - pts_m[0][1]
            if r['rtype'] == 'Jalan MR' and dx_c < 0:
                pts_m.reverse()
            elif r['rtype'] == 'Jalan CR' and dy_c < 0:
                pts_m.reverse()
            elif (dx_c + dy_c) < 0:
                pts_m.reverse()
            cl_deg = [pt_to_deg(p) for p in pts_m]
            cL = math.hypot(pts_m[-1][0] - pts_m[0][0], pts_m[-1][1] - pts_m[0][1]) or 1.0
            ux = (pts_m[-1][0] - pts_m[0][0]) / cL
            uy = (pts_m[-1][1] - pts_m[0][1]) / cL
            pmin = pts_m[0][0] * ux + pts_m[0][1] * uy
            axis_len_m = round(LineString(pts_m).length, 1)
            road_id = len(road_geojson_features)
            road_geojson_features.append({
                'type': 'Feature',
                'properties': {
                    'road_id': road_id,
                    'estate': r['estate'],
                    'divisi': r['divisi'],
                    'blok': r['blok'],
                    'neighbor_blok': r['neighbor'] or '-',
                    'antar_blok': antar_blok,
                    'keterangan': r['rtype'],
                    'lebar_m': r['width'],
                    'panjang_m': panjang_m,
                    'hectare': ha,
                    'ukuran': f"{panjang_m} m",
                    'axis_ux': round(ux, 5),
                    'axis_uy': round(uy, 5),
                    'axis_pmin': round(pmin, 2),
                    'axis_len_m': axis_len_m,
                    'centerline': cl_deg
                },
                'geometry': geom_m_to_geojson(clean_geom)
            })

    # 3b. Add outside Jalan Raya / Jalan Akses corridors
    for hw in DEFAULT_HIGHWAY_CORRIDORS:
        cl_deg = hw['centerline']
        pts_m = [pt_to_m(p) for p in cl_deg]
        ls_m = LineString(pts_m)
        w_half = hw['lebar_m'] / 2.0
        buf_m = make_valid(ls_m.buffer(w_half, cap_style='flat', join_style='round'))
        area_m2 = buf_m.area
        ha = round(area_m2 / 10000.0, 4)
        panjang_m = round(ls_m.length, 1)
        cL = math.hypot(pts_m[-1][0] - pts_m[0][0], pts_m[-1][1] - pts_m[0][1]) or 1.0
        ux = (pts_m[-1][0] - pts_m[0][0]) / cL
        uy = (pts_m[-1][1] - pts_m[0][1]) / cL
        pmin = pts_m[0][0] * ux + pts_m[0][1] * uy
        road_id = len(road_geojson_features)
        road_geojson_features.append({
            'type': 'Feature',
            'properties': {
                'road_id': road_id,
                'estate': hw['estate'],
                'divisi': hw['divisi'],
                'blok': hw['blok'],
                'neighbor_blok': '-',
                'antar_blok': hw['antar_blok'],
                'keterangan': hw['keterangan'],
                'lebar_m': hw['lebar_m'],
                'panjang_m': panjang_m,
                'hectare': ha,
                'ukuran': f"{panjang_m} m",
                'axis_ux': round(ux, 5),
                'axis_uy': round(uy, 5),
                'axis_pmin': round(pmin, 2),
                'axis_len_m': panjang_m,
                'centerline': cl_deg
            },
            'geometry': geom_m_to_geojson(buf_m)
        })

    # 4. Subtract road corridors from named blocks to form inset 'Areal Tanam' polygons
    block_geojson_features = []
    for i in range(len(named_feats)):
        if block_cuts[i]:
            pg = make_valid(geoms_m[i].difference(unary_union(block_cuts[i])))
            if pg.geom_type == 'GeometryCollection':
                polys = [g for g in pg.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
                pg = unary_union(polys) if polys else Polygon()
        else:
            pg = geoms_m[i]

        ha = round(pg.area / 10000.0, 2)
        block_geojson_features.append({
            'type': 'Feature',
            'properties': {
                'estate': estates[i],
                'divisi': divisis[i],
                'blok': bloks[i],
                'keterangan': 'Areal Tanam',
                'hectare': ha,
                'ukuran': f"{ha} Ha"
            },
            'geometry': geom_m_to_geojson(pg)
        })

    # 5. Clean unnamed enclaves (remove <4m topology slivers that overlap road corridors)
    for uf in unnamed_feats:
        u_geom_m = geom_to_m(shape(uf['geometry'])).buffer(0)
        u_polys = [u_geom_m] if u_geom_m.geom_type == 'Polygon' else [
            p for p in u_geom_m.geoms if p.geom_type == 'Polygon'
        ]
        kept_polys = []
        for p in u_polys:
            mean_width_m = (2.0 * p.area / p.length) if p.length > 0 else 0.0
            ha_p = p.area / 10000.0
            if mean_width_m >= 4.0 and ha_p >= 0.05:
                kept_polys.append(p)
        if kept_polys:
            clean_u = unary_union(kept_polys)
            ha = round(clean_u.area / 10000.0, 2)
            props = dict(uf.get('properties', {}))
            props['keterangan'] = 'Non-Tanam / Enclave'
            props['hectare'] = ha
            props['ukuran'] = f"{ha} Ha"
            block_geojson_features.append({
                'type': 'Feature',
                'properties': props,
                'geometry': geom_m_to_geojson(clean_u)
            })

    blocks_fc = {
        'type': 'FeatureCollection',
        'name': 'PMSE_JLYE_Blocks',
        'crs': crs_info,
        'features': block_geojson_features
    }

    roads_fc = {
        'type': 'FeatureCollection',
        'name': 'PMSE_JLYE_Roads',
        'crs': crs_info,
        'features': road_geojson_features
    }

    # Build spatial index for telemetry matching
    blocks_index = []
    for feat in block_geojson_features:
        props = feat.get('properties', {})
        geom = feat.get('geometry', {})
        gtype = geom.get('type')
        rings = []
        if gtype == 'Polygon' and geom.get('coordinates'):
            rings.append(geom['coordinates'][0])
        elif gtype == 'MultiPolygon':
            for poly in geom.get('coordinates', []):
                if poly:
                    rings.append(poly[0])
        for r in rings:
            lons = [pt[0] for pt in r]
            lats = [pt[1] for pt in r]
            blocks_index.append({
                'estate': str(props.get('estate', 'PMSE')),
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
        json.dump(blocks_fc, f, separators=(',', ':'))
    print(f"Saved {output_path} ({len(block_geojson_features)} features, {os.path.getsize(output_path) / 1024:.1f} KB)")

    if roads_output_path:
        os.makedirs(os.path.dirname(roads_output_path), exist_ok=True)
        with open(roads_output_path, 'w', encoding='utf-8') as f:
            json.dump(roads_fc, f, separators=(',', ':'))
        print(f"Saved {roads_output_path} ({len(road_geojson_features)} road features, {os.path.getsize(roads_output_path) / 1024:.1f} KB)")

    if combined_output_path:
        combined_fc = {
            'type': 'FeatureCollection',
            'name': 'PMSE_JLYE_Blocks_and_Roads',
            'crs': crs_info,
            'features': block_geojson_features + road_geojson_features
        }
        with open(combined_output_path, 'w', encoding='utf-8') as f:
            json.dump(combined_fc, f, separators=(',', ':'))
        print(f"Saved {combined_output_path} ({len(combined_fc['features'])} total features, {os.path.getsize(combined_output_path) / 1024:.1f} KB)")

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
        return '', '', ''
    # 1. Exact point-in-polygon check
    for b in blocks_index:
        if b['min_lat'] <= lat <= b['max_lat'] and b['min_lon'] <= lon <= b['max_lon']:
            if point_in_poly(lon, lat, b['ring']):
                return b['blok'], b['divisi'], b.get('estate', 'PMSE')

    # 2. Boundary road corridor fallback (~200m / 0.0018 deg)
    best_d2 = 0.0018 ** 2
    best_match = ('Jalan Raya', 'LUAR BLOK', 'LUAR KEBUN')
    for b in blocks_index:
        if (b['min_lat'] - 0.0018 <= lat <= b['max_lat'] + 0.0018 and
                b['min_lon'] - 0.0018 <= lon <= b['max_lon'] + 0.0018):
            r = b['ring']
            for i in range(len(r) - 1):
                d2 = dist_sq_to_segment(lon, lat, r[i][0], r[i][1], r[i + 1][0], r[i + 1][1])
                if d2 < best_d2:
                    best_d2 = d2
                    best_match = (b['blok'], b['divisi'], b.get('estate', 'PMSE'))
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
            if fname == '23000988-20261103133554.txt':
                continue
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
        blok, divisi, estate = match_block_and_divisi(mid_pt[0], mid_pt[1], blocks_index)

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
            'estate': estate,
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
        [os.path.join(BASE_DIR, 'PMSE.json'), os.path.join(BASE_DIR, 'JLYE.json')],
        os.path.join(web_data_dir, 'pmse_blocks.json'),
        roads_output_path=os.path.join(web_data_dir, 'pmse_roads.json'),
        combined_output_path=os.path.join(BASE_DIR, 'PMSE_with_roads.json')
    )

    datasets = {
        '20261103': [
            '../Accelerometer Data - 23000889_20261103-20261103/Accelerometer Data.csv',
            'ROSE/Accelerometer Data - 23000889_20261103-20261103/Accelerometer Data.csv',
        ],
        '20261104': [
            '../Accelerometer Data - 23000988_20261104-20261104 A27/Accelerometer Data.csv',
            'ROSE/Accelerometer Data - 23000988_20261104-20261104 A27/Accelerometer Data.csv',
        ],
        '20261105': [
            '../Accelerometer Data - 23000988_20261105-20261105/Accelerometer Data.csv',
            'ROSE/Accelerometer Data - 23000988_20261105-20261105/Accelerometer Data.csv',
        ],
        '20261106': [
            '../Accelerometer Data - 23000988_20261106-20261106/Accelerometer Data.csv',
            'ROSE/Accelerometer Data - 23000988_20261106-20261106/Accelerometer Data.csv',
        ],
    }

    runs = {}
    for dt, rel_csv_list in datasets.items():
        out_json = os.path.join(web_data_dir, f'data_{dt}.json')
        found_csv = None
        for rel_csv in rel_csv_list:
            cand = os.path.normpath(os.path.join(BASE_DIR, rel_csv))
            if os.path.exists(cand):
                found_csv = cand
                break
        if found_csv:
            runs[dt] = process_csv(
                found_csv,
                out_json,
                dt,
                blocks_idx
            )
        elif os.path.exists(out_json):
            with open(out_json, 'r', encoding='utf-8') as f:
                segs = json.load(f)
            # Re-match block, divisi, and estate against combined PMSE + JLYE blocks_idx
            for s in segs:
                c = s.get('coords', [])
                if c:
                    mid_pt = c[len(c) // 2]
                    blok, divisi, estate = match_block_and_divisi(mid_pt[0], mid_pt[1], blocks_idx)
                    s['blok'] = blok
                    s['divisi'] = divisi
                    s['estate'] = estate
            with open(out_json, 'w', encoding='utf-8') as f:
                json.dump(segs, f, separators=(',', ':'))
            print(f"Updated {out_json} with PMSE + JLYE block/estate matching ({len(segs)} segments)")
            runs[dt] = segs

    if runs:
        compute_stats(runs, os.path.join(web_data_dir, 'summary_stats.json'))
    print("Data preparation complete!")
