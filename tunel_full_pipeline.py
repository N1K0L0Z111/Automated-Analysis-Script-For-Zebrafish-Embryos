import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, simpledialog
import numpy as np
import pandas as pd
from PIL import Image

# Default paths for ImageJ and macro
DEFAULT_IMAGEJ = Path(r"C:\Users\chakhu17.000\Downloads\ij154-win-java8\ImageJ\ImageJ.exe")
DEFAULT_MACRO  = Path(r"C:\Users\chakhu17\Desktop\process_tunel_40x.ijm")


def analyze_image_color(full_path):
    """
    Evaluates foreground color signals (top 5% brightest pixels) to ignore camera background noise.
    Returns:
        greenness_score: (Foreground Green - Foreground Blue) difference
        fg_g: Mean foreground Green intensity
        fg_b: Mean foreground Blue intensity
    """
    try:
        im = Image.open(full_path).convert('RGB')
        arr = np.array(im, dtype=float)
        
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        
        # Difference map
        diff = g - b
        
        # Foreground mask (top 5% brightest pixels in R+G+B)
        brightness = r + g + b
        p95 = np.percentile(brightness, 95)
        mask = brightness >= p95
        
        if np.sum(mask) > 0:
            fg_g = np.mean(g[mask])
            fg_b = np.mean(b[mask])
            greenness_score = np.mean(diff[mask])
        else:
            fg_g = np.mean(g)
            fg_b = np.mean(b)
            greenness_score = np.mean(diff)
            
        return greenness_score, fg_g, fg_b
    except Exception as e:
        print(f"Error analyzing color for {full_path}: {e}")
        return 0.0, 0.0, 0.0


def get_condition_and_prefix(filename):
    """Extract condition tag (mAk/oAk) and sample prefix from raw filename."""
    if not filename:
        return "", ""
    stem = re.sub(r'\.(tif|tiff|jpg|jpeg|png)$', '', Path(filename).name, flags=re.IGNORECASE)
    
    cond = ""
    prefix = stem
    
    if re.search(r'oAk', stem, re.IGNORECASE):
        cond = 'oAk'
        prefix = re.sub(r'[_\-\s]*oAk.*$', '', stem, flags=re.IGNORECASE)
    elif re.search(r'mAk', stem, re.IGNORECASE):
        cond = 'mAk'
        prefix = re.sub(r'[_\-\s]*mAk.*$', '', stem, flags=re.IGNORECASE)
    elif re.search(r'\bAK\b', stem, re.IGNORECASE) or re.search(r'_AK[_\-\s]', stem, re.IGNORECASE):
        cond = 'mAk'
        prefix = re.sub(r'[_\-\s]*AK.*$', '', stem, flags=re.IGNORECASE)

    prefix = prefix.strip('_- ')
    return cond, prefix


def generate_pair_names(dapi_filename, tunel_filename, idx):
    """Build new filenames that preserve sample key and mAk/oAk condition tags."""
    cond_d, pref_d = get_condition_and_prefix(dapi_filename) if dapi_filename else ("", "")
    cond_t, pref_t = get_condition_and_prefix(tunel_filename) if tunel_filename else ("", "")
    
    cond = cond_d or cond_t
    prefix = pref_d or pref_t
    
    # Clean generic prefixes like 'brain_01' to avoid duplicate naming
    if re.match(r'^brain[_\-\s]*\d+$', prefix, re.IGNORECASE):
        prefix = ""

    def make_name(channel):
        parts = []
        if prefix:
            parts.append(prefix)
        if cond:
            parts.append(cond)
        parts.append(f"Brain_{idx:02d}")
        parts.append(f"{channel}.tif")
        return "_".join(parts)

    new_dapi = make_name("dapi") if dapi_filename else None
    new_tunel = make_name("tunel") if tunel_filename else None
    
    return new_dapi, new_tunel


def run_color_verified_renaming(folder_path):
    print("\n--- STEP 1: Color-Verified Renaming & Pairing ---")
    valid_exts = ('.tif', '.tiff', '.jpg', '.png')
    
    # Exclude temp files, masks, or files already renamed with channel tags
    files = [
        f for f in os.listdir(folder_path) 
        if f.lower().endswith(valid_exts) 
        and '_qc_mask' not in f.lower() 
        and 'temp_' not in f.lower() 
        and not re.search(r'_(dapi|tunel)\.(tif|tiff|jpg|png)$', f, re.IGNORECASE)
    ]
    
    if not files:
        print("Files appear to already be renamed or no raw files found. Proceeding to TUNEL analysis...")
        return

    file_records = []
    print("Analyzing image color channels with foreground masking...")
    for f in files:
        full_path = os.path.join(folder_path, f)
        try:
            mtime = os.path.getmtime(full_path)
            score, fg_g, fg_b = analyze_image_color(full_path)
            
            file_records.append({
                'filename': f,
                'path': full_path,
                'mtime': mtime,
                'greenness_score': score,
                'fg_g': fg_g,
                'fg_b': fg_b
            })
        except Exception as e:
            print(f"Error reading {f}: {e}")

    file_records.sort(key=lambda x: x['mtime'])

    # Group into pairs captured within 3 minutes (180 seconds)
    pairs = []
    used = set()
    for i in range(len(file_records)):
        if i in used:
            continue
        current = file_records[i]
        current_group = [current]
        used.add(i)
        
        for j in range(i + 1, len(file_records)):
            if j in used:
                continue
            other = file_records[j]
            if abs(other['mtime'] - current['mtime']) <= 180:
                current_group.append(other)
                used.add(j)
                break
        pairs.append(current_group)

    rename_plan = []
    for idx, group in enumerate(pairs, start=1):
        if len(group) == 2:
            # Pairwise relative comparison: higher greenness score is TUNEL, lower is DAPI
            score0 = group[0]['greenness_score']
            score1 = group[1]['greenness_score']
            if score0 > score1:
                tunel_item = group[0]
                dapi_item = group[1]
            else:
                dapi_item = group[0]
                tunel_item = group[1]
        else:
            # Standalone single image classification
            item = group[0]
            if item['fg_g'] >= item['fg_b'] or item['greenness_score'] >= -1.0:
                tunel_item = item
                dapi_item = None
            else:
                dapi_item = item
                tunel_item = None

        d_fn = dapi_item['filename'] if dapi_item else None
        t_fn = tunel_item['filename'] if tunel_item else None

        new_dapi, new_tunel = generate_pair_names(d_fn, t_fn, idx)

        if dapi_item and new_dapi:
            rename_plan.append((dapi_item['path'], os.path.join(folder_path, new_dapi)))
        if tunel_item and new_tunel:
            rename_plan.append((tunel_item['path'], os.path.join(folder_path, new_tunel)))

    if rename_plan:
        # Safe two-stage rename to prevent filename collisions
        temp_list = []
        for old_path, final_path in rename_plan:
            d, fn = os.path.split(final_path)
            tmp_path = os.path.join(d, "temp_" + fn)
            os.rename(old_path, tmp_path)
            temp_list.append((tmp_path, final_path))
        
        for tmp_path, final_path in temp_list:
            os.rename(tmp_path, final_path)
        print(f"Successfully renamed and paired {len(rename_plan)} files with robust channel verification.")


def run_tunel_quantification(imagej_exec, macro_path, image_dir, final_csv, sensitivity):
    print("\n--- STEP 2: TUNEL Quantification Pipeline ---")
    raw_csv = image_dir / "tunel_raw_results_temp.csv"

    if raw_csv.exists():
        try:
            raw_csv.unlink()
        except PermissionError:
            sys.exit(f"ERROR: '{raw_csv.name}' is open in Excel or another program. Close it and retry.")

    input_dir_str = image_dir.as_posix()
    if not input_dir_str.endswith('/'):
        input_dir_str += '/'
    output_csv_str = raw_csv.as_posix()
    macro_args = f"{input_dir_str}*{output_csv_str}*{sensitivity}"

    command = [
        str(imagej_exec),
        "-macro", str(macro_path.as_posix()),
        macro_args
    ]

    print("Launching ImageJ for DAPI brain region ROI selection...")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.stdout and result.stdout.strip():
        print("\n--- ImageJ Output Log ---")
        print(result.stdout.strip())
    if result.stderr and result.stderr.strip():
        print("\n--- ImageJ Warnings/Errors ---")
        print(result.stderr.strip())

    process_results(raw_csv, final_csv, image_dir)


def parse_condition_and_sample_key(label):
    stem = re.sub(r'\.(tif|tiff|jpg|jpeg|png)$', '', str(label), flags=re.IGNORECASE)
    if re.search(r'oAk', stem, re.IGNORECASE):
        group_type = 'oAk'
        sample_key = re.sub(r'[_\-\s]*oAk.*$', '', stem, flags=re.IGNORECASE)
    elif re.search(r'mAk', stem, re.IGNORECASE):
        group_type = 'mAk'
        sample_key = re.sub(r'[_\-\s]*mAk.*$', '', stem, flags=re.IGNORECASE)
    elif re.search(r'\bAK\b', stem, re.IGNORECASE) or re.search(r'_AK[_\-\s]', stem, re.IGNORECASE):
        group_type = 'mAk'
        sample_key = re.sub(r'[_\-\s]*AK.*$', '', stem, flags=re.IGNORECASE)
    else:
        group_type = 'Sample'
        sample_key = stem
    return group_type, sample_key


def process_results(raw_csv, final_csv, image_dir):
    if not raw_csv.exists():
        print(f"\n[WARNING] Temp output CSV not found at {raw_csv}.")
        return

    df = None
    for enc in ['utf-8', 'cp1252', 'latin1', 'utf-16']:
        try:
            df = pd.read_csv(raw_csv, encoding=enc)
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    if df is None or df.empty:
        print("\n[WARNING] The output CSV is empty (0 data rows recorded).")
        return

    df.columns = df.columns.str.strip()
    if 'Label' not in df.columns:
        print("\n[WARNING] 'Label' column missing from output CSV.")
        return

    parsed_info = df['Label'].apply(parse_condition_and_sample_key)
    parsed_df = pd.DataFrame(parsed_info.tolist(), index=df.index, columns=['Group_Type', 'Sample_Key'])
    df[['Group_Type', 'Sample_Key']] = parsed_df

    oak_df = df[df['Group_Type'] == 'oAk']
    oak_nifi_lookup = oak_df.groupby('Sample_Key')['NIFI'].mean().to_dict() if not oak_df.empty else {}
    df['Matched_oAk_NIFI'] = df['Sample_Key'].map(oak_nifi_lookup)

    def calc_delta_nifi(row):
        if row['Group_Type'] == 'mAk':
            if pd.notna(row['Matched_oAk_NIFI']):
                return row['NIFI'] - row['Matched_oAk_NIFI']
            return None
        elif row['Group_Type'] == 'oAk':
            return 0.0
        return None

    df['Delta_NIFI_mAk_minus_oAk'] = df.apply(calc_delta_nifi, axis=1)
    df_export = df.drop(columns=['Sample_Key'])
    df_export.to_csv(final_csv, index=False, encoding='utf-8')

    if raw_csv.exists():
        raw_csv.unlink()

    print("\n================ FINAL BATCH RESULTS ================")
    print(f"Results saved to: {final_csv}\n")
    for _, r in df_export.iterrows():
        status = r.get('Status', 'Processed')
        group = r.get('Group_Type', 'Sample')
        if status != "No Brain":
            delta_str = f"{r['Delta_NIFI_mAk_minus_oAk']:.6f}" if pd.notna(r['Delta_NIFI_mAk_minus_oAk']) else "N/A"
            print(f"Image: {r['Label']:35s} [{group:4s}] | NIFI: {r['NIFI']:.6f} | Delta: {delta_str}")


if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    image_dir = filedialog.askdirectory(title="Select Folder Containing Zebrafish Images")
    if not image_dir:
        sys.exit("Cancelled.")
    image_dir = Path(image_dir)

    # 1. Color-verified pairing (with faint signal protection)
    run_color_verified_renaming(image_dir)

    # 2. Executables & destination selection
    imagej_exec = DEFAULT_IMAGEJ
    if not imagej_exec.exists():
        selected_ij = filedialog.askopenfilename(title="Select ImageJ.exe File", filetypes=[("Executable Files", "*.exe")])
        if not selected_ij: sys.exit("Cancelled.")
        imagej_exec = Path(selected_ij)

    macro_path = DEFAULT_MACRO
    if not macro_path.exists():
        selected_macro = filedialog.askopenfilename(title="Select TUNEL Macro File (.ijm)", filetypes=[("ImageJ Macro", "*.ijm")])
        if not selected_macro: sys.exit("Cancelled.")
        macro_path = Path(selected_macro)

    final_csv = filedialog.asksaveasfilename(
        title="Save Compiled TUNEL CSV Results As...",
        defaultextension=".csv",
        initialfile="compiled_tunel_results_40x.csv",
        filetypes=[("CSV Files", "*.csv")]
    )
    if not final_csv: sys.exit("Cancelled.")
    final_csv = Path(final_csv)

    prompt_msg = """Set signal detection threshold sensitivity (StdDev Multiplier k):

• Cutoff = Mean_Brain + (k * StdDev_Brain)
• Default: 0.75
• Higher sensitivity (detects fainter signal): 0.50 - 0.65
• Lower sensitivity (stricter / brighter signal only): 0.85 - 1.20

Enter value:"""

    sensitivity = simpledialog.askfloat(
        "TUNEL Signal Sensitivity Settings",
        prompt_msg,
        initialvalue=0.75,
        minvalue=0.05,
        maxvalue=4.00,
        parent=root
    )

    if sensitivity is None:
        sensitivity = 0.75
        print("Sensitivity prompt closed; using default value: 0.75")
    else:
        print(f"Signal detection sensitivity set to: {sensitivity:.2f}")

    root.destroy()

    # 3. Execution
    run_tunel_quantification(imagej_exec, macro_path, image_dir, final_csv, sensitivity)
    