import os
import json
import argparse


def restore_video_names(manifest_path=None, video_root=None, dry_run=False):
    if manifest_path is None:
        manifest_path = os.path.join(os.path.dirname(__file__), 'video_manifest.json')

    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    root = video_root or manifest.get('video_root', r'D:\RoSe\Video')
    print(f"Manifest : {manifest_path}")
    print(f"VideoDir : {root}")
    print(f"Mode     : {'DRY RUN (no changes)' if dry_run else 'LIVE RENAME'}")
    print("-" * 60)

    total_ok = 0
    total_renamed = 0
    total_missing = 0

    for folder_name, entries in manifest.get('dates', {}).items():
        folder_path = os.path.join(root, folder_name)
        if not os.path.isdir(folder_path):
            print(f"[SKIP] Folder not found: {folder_path}")
            continue

        # Map exact size_bytes -> target_filename
        size_to_target = {item['size_bytes']: item['target_filename'] for item in entries}

        # Scan current mp4 files in folder
        current_by_size = {}
        for fname in os.listdir(folder_path):
            if not fname.lower().endswith('.mp4'):
                continue
            fpath = os.path.join(folder_path, fname)
            fsize = os.path.getsize(fpath)
            current_by_size[fsize] = fname

        print(f"\n[{folder_name}] ({len(entries)} expected)")

        # Step 1: Identify files that need renaming and move to temp names first to prevent collisions
        pending_renames = []
        for size_bytes, target_name in size_to_target.items():
            cur_name = current_by_size.get(size_bytes)
            if not cur_name:
                print(f"  [MISSING] {target_name} ({size_bytes:,} bytes)")
                total_missing += 1
            elif cur_name == target_name:
                total_ok += 1
            else:
                pending_renames.append((cur_name, target_name, size_bytes))

        if not pending_renames:
            print(f"  All {len(entries) - total_missing} present files already match calibrated names.")
            continue

        if dry_run:
            for cur_name, target_name, size_bytes in pending_renames:
                print(f"  [WOULD RENAME] {cur_name} -> {target_name} ({size_bytes:,} bytes)")
                total_renamed += 1
        else:
            temp_moves = []
            for cur_name, target_name, size_bytes in pending_renames:
                src = os.path.join(folder_path, cur_name)
                tmp = os.path.join(folder_path, f"__tmp_{size_bytes}.mp4")
                os.rename(src, tmp)
                temp_moves.append((tmp, cur_name, target_name))

            for tmp, cur_name, target_name in temp_moves:
                dst = os.path.join(folder_path, target_name)
                os.rename(tmp, dst)
                print(f"  [RENAMED] {cur_name} -> {target_name}")
                total_renamed += 1

    print("\n" + "=" * 60)
    print(f"Summary: {total_ok} already OK | {total_renamed} renamed | {total_missing} missing")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Restore calibrated RoSe video filenames by exact file size.')
    parser.add_argument('--manifest', help='Path to video_manifest.json')
    parser.add_argument('--video-root', help='Root directory containing date folders')
    parser.add_argument('--dry-run', action='store_true', help='Preview renames without modifying files')
    args = parser.parse_args()
    restore_video_names(args.manifest, args.video_root, args.dry_run)
