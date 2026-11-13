import os
import struct
from datetime import datetime, timedelta
import json

# Known date to folder mappings
DATE_FOLDER_NAMES = {
    '20261103': ['03 Nov 2026', '20261103', '3 Nov 2026'],
    '20261104': ['04 Nov 2026', '20261104', '4 Nov 2026'],
    '20261105': ['05 Nov 2026', '20261105', '5 Nov 2026'],
    '20261106': ['06 Nov 2026', '20261106', '6 Nov 2026'],
}

BASE_SEARCH_ROOTS = [
    r'D:\RoSe\Video',
    r'D:\RoSe\ROSE\Video',
    os.path.abspath(os.path.join(os.path.dirname(__file__), 'ROSE', 'Video')),
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Video')),
    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'Video')),
]

def get_mp4_duration(filepath):
    """
    Fast pure-python MP4 duration parser from mvhd atom.
    Does not require external libraries.
    """
    try:
        with open(filepath, 'rb') as f:
            while True:
                header = f.read(8)
                if len(header) < 8:
                    break
                size, atom_type = struct.unpack('>I4s', header)
                atom_name = atom_type.decode('ascii', errors='ignore')
                if size == 1:
                    size = struct.unpack('>Q', f.read(8))[0]
                    payload_len = size - 16
                elif size == 0:
                    break
                else:
                    payload_len = size - 8

                if atom_name == 'moov':
                    moov_bytes = f.read(payload_len)
                    idx = moov_bytes.find(b'mvhd')
                    if idx != -1:
                        ver = moov_bytes[idx + 4]
                        if ver == 0:
                            scale, dur = struct.unpack('>II', moov_bytes[idx + 16:idx + 24])
                        else:
                            scale, dur = struct.unpack('>IQ', moov_bytes[idx + 24:idx + 36])
                        return (dur / scale) if scale > 0 else 0.0
                    return 0.0
                else:
                    f.seek(payload_len, 1)
    except Exception:
        pass
    return 0.0


def locate_date_folder(date_str):
    """
    Locates the folder containing videos for a specific date.
    """
    candidates = DATE_FOLDER_NAMES.get(date_str, [date_str])
    for root in BASE_SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for cand in candidates:
            p = os.path.join(root, cand)
            if os.path.isdir(p):
                return p
        # Also check direct child folders matching date
        for entry in os.listdir(root):
            entry_path = os.path.join(root, entry)
            if os.path.isdir(entry_path) and (date_str in entry or any(c in entry for c in candidates)):
                return entry_path
    return None


def get_available_video_dates():
    """
    Returns list of dates that currently have videos available.
    """
    found_dates = {}
    for d, cands in DATE_FOLDER_NAMES.items():
        fld = locate_date_folder(d)
        if fld:
            mp4s = [f for f in os.listdir(fld) if f.lower().endswith('.mp4')]
            if mp4s:
                label = f"{d[6:8]} Nov {d[:4]}"
                found_dates[d] = {
                    'date': d,
                    'label': label,
                    'count': len(mp4s),
                    'folder': fld
                }
    return list(found_dates.values())


# Cache for video lists so repeated queries are instant
_VIDEO_CACHE = {}

def list_videos_for_date(date_str, force_refresh=False):
    """
    Returns sorted list of video metadata for a given date.
    Automatically detects file renames/additions in the folder.
    """
    folder = locate_date_folder(date_str)
    if not folder:
        return []

    mp4_files = tuple(sorted(f for f in os.listdir(folder) if f.lower().endswith('.mp4')))
    if not force_refresh and date_str in _VIDEO_CACHE:
        cached_key, cached_results = _VIDEO_CACHE[date_str]
        if cached_key == mp4_files:
            return cached_results

    results = []
    for fname in mp4_files:
        p = os.path.join(folder, fname)
        size_bytes = os.path.getsize(p)
        dur = get_mp4_duration(p)

        # Parse timestamp from filename: YYYYMMDD_HHMMSS.mp4
        start_time_iso = None
        end_time_iso = None
        start_dt = None
        end_dt = None
        stem = os.path.splitext(fname)[0]
        try:
            # Handles '20261104_094725'
            parts = stem.split('_')
            if len(parts) >= 2 and len(parts[0]) == 8 and len(parts[1]) >= 6:
                dt_str = f"{parts[0]}_{parts[1][:6]}"
                start_dt = datetime.strptime(dt_str, '%Y%m%d_%H%M%S')
                end_dt = start_dt + timedelta(seconds=dur)
                start_time_iso = start_dt.isoformat()
                end_time_iso = end_dt.isoformat()
        except Exception:
            pass

        results.append({
            'file': fname,
            'path': p,
            'size_bytes': size_bytes,
            'size_mb': round(size_bytes / (1024 * 1024), 1),
            'duration': round(dur, 2),
            'duration_formatted': f"{int(dur // 60):02d}:{int(dur % 60):02d}",
            'start_time': start_time_iso,
            'end_time': end_time_iso,
            'start_dt': start_dt.timestamp() if start_dt else None,
            'end_dt': end_dt.timestamp() if end_dt else None,
            'stream_url': f"/video/stream?date={date_str}&file={fname}"
        })

    # Sort primarily by start_dt if available, else by file name
    results.sort(key=lambda x: (x['start_dt'] or 0, x['file']))
    _VIDEO_CACHE[date_str] = (mp4_files, results)
    return results


def resolve_video_file(date_str, filename):
    """
    Resolves the absolute path of a video file.
    """
    vids = list_videos_for_date(date_str)
    if filename:
        for v in vids:
            if v['file'] == filename:
                return v['path']
        # Fallback direct check
        folder = locate_date_folder(date_str)
        if folder:
            direct_path = os.path.join(folder, filename)
            if os.path.exists(direct_path):
                return direct_path
    elif vids:
        return vids[0]['path']
    return None


def match_segment_to_video(date_str, segment_timestamp_iso):
    """
    Given a segment timestamp, finds the encompassing video and seek offset in seconds.
    """
    try:
        # segment_timestamp_iso: e.g. "2026-11-04T09:50:33.593"
        seg_dt = datetime.fromisoformat(segment_timestamp_iso.replace('Z', ''))
        seg_epoch = seg_dt.timestamp()

        vids = list_videos_for_date(date_str)
        for v in vids:
            if v['start_dt'] and v['end_dt']:
                # Allow a small 2-second margin on edges
                if (v['start_dt'] - 2.0) <= seg_epoch <= (v['end_dt'] + 2.0):
                    seek_offset = max(0.0, seg_epoch - v['start_dt'])
                    return {
                        'matched': True,
                        'file': v['file'],
                        'seek_seconds': round(seek_offset, 2),
                        'video_start': v['start_time'],
                        'video_end': v['end_time'],
                        'stream_url': v['stream_url']
                    }
    except Exception as e:
        return {'matched': False, 'error': str(e)}

    return {'matched': False}


def get_groundtruth_path(date_str):
    data_dir = os.path.join(os.path.dirname(__file__), 'web', 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, f'groundtruth_{date_str}.json')


def load_groundtruth(date_str):
    p = get_groundtruth_path(date_str)
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_groundtruth(date_str, annotations):
    p = get_groundtruth_path(date_str)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(annotations, f, indent=2)
        return True
    except Exception:
        return False


def get_video_settings_path():
    data_dir = os.path.join(os.path.dirname(__file__), 'web', 'data')
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, 'video_settings.json')


def load_video_settings():
    p = get_video_settings_path()
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_video_settings(settings):
    p = get_video_settings_path()
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception:
        return False

