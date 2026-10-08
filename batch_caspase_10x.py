#----------Caspase Assay Script for 10x brain------------#



import subprocess
import pandas as pd
from pathlib import Path
import sys
import re
import tkinter as tk
from tkinter import filedialog, simpledialog

# Default paths
DEFAULT_IMAGEJ = Path(r"C:\Users\chakhu17.000\Downloads\ij154-win-java8\ImageJ\ImageJ.exe")
DEFAULT_MACRO  = Path(r"C:\Users\chakhu17\Desktop\process_caspase_10x_semi.ijm")


def select_files_interactive():
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    # 1. ImageJ Executable check
    imagej_exec = DEFAULT_IMAGEJ
    if not imagej_exec.exists():
        print("Locate your ImageJ.exe file...")
        selected_ij = filedialog.askopenfilename(
            title="Select ImageJ.exe File",
            filetypes=[("Executable Files", "*.exe")]
        )
        if not selected_ij:
            sys.exit("Cancelled: ImageJ executable required.")
        imagej_exec = Path(selected_ij)

    # 2. Macro file check
    macro_path = DEFAULT_MACRO
    if not macro_path.exists():
        selected_macro = filedialog.askopenfilename(
            title="Select ImageJ Macro File (.ijm)",
            filetypes=[("ImageJ Macro", "*.ijm")]
        )
        if not selected_macro:
            sys.exit("Cancelled: Macro file required.")
        macro_path = Path(selected_macro)

    # 3. Select Input Image Directory
    print("Select input directory containing 10x Caspase images...")
    image_dir = filedialog.askdirectory(title="Select Input Image Directory")
    if not image_dir:
        sys.exit("Cancelled: Input directory required.")
    image_dir = Path(image_dir)

    # 4. Select Output CSV File
    print("Select destination and filename for final compiled CSV...")
    final_csv = filedialog.asksaveasfilename(
        title="Save Compiled CSV Results As...",
        defaultextension=".csv",
        initialfile="compiled_caspase_results_10x.csv",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    if not final_csv:
        sys.exit("Cancelled: Output CSV path required.")
    final_csv = Path(final_csv)

    # 5. Sensitivity Adjustment Dialog Window
    sensitivity = simpledialog.askfloat(
        "Signal Detection Sensitivity",
        "Set signal detection threshold sensitivity (StdDev Multiplier):\n\n"
        "• Default: 0.75\n"
        "• Higher sensitivity (detects fainter signal): 0.50 - 0.65\n"
        "• Lower sensitivity (stricter / darker signal only): 0.85 - 1.20\n\n"
        "Enter value:",
        initialvalue=0.75,
        minvalue=0.05,
        maxvalue=3.00,
        parent=root
    )
    if sensitivity is None:
        sensitivity = 0.75
        print("Sensitivity prompt closed; using default value: 0.75")
    else:
        print(f"Signal detection sensitivity set to: {sensitivity}")

    return imagej_exec, macro_path, image_dir, final_csv, sensitivity


def run_imagej_batch(imagej_exec, macro_path, image_dir, final_csv, sensitivity):
    raw_csv = image_dir / "caspase_raw_results_temp.csv"

    # Reset temp CSV
    if raw_csv.exists():
        raw_csv.unlink()

    input_dir_str = image_dir.as_posix()
    output_csv_str = raw_csv.as_posix()
    macro_args = f"{input_dir_str}*{output_csv_str}*{sensitivity}"

    command = [
        str(imagej_exec),
        "-macro", str(macro_path.as_posix()),
        macro_args
    ]

    print("\nLaunching ImageJ for brain region selection...")
    subprocess.run(command)

    process_results(raw_csv, final_csv, image_dir)


def parse_ab_type_and_key(label):
    if re.search(r'oAK', label, re.IGNORECASE):
        ab_type = 'oAK'
        pair_key = re.sub(r'oAK', 'MATCH_KEY', label, flags=re.IGNORECASE)
    elif re.search(r'AK', label, re.IGNORECASE):
        ab_type = 'AK'
        pair_key = re.sub(r'AK', 'MATCH_KEY', label, flags=re.IGNORECASE)
    else:
        ab_type = 'Unknown'
        pair_key = label
    return pd.Series([ab_type, pair_key])


def process_results(raw_csv, final_csv, image_dir):
    if not raw_csv.exists():
        sys.exit(f"STOPPING: Output CSV not found at {raw_csv}")

    df = None
    for enc in ['utf-8', 'cp1252', 'latin1', 'utf-16']:
        try:
            df = pd.read_csv(raw_csv, encoding=enc)
            break
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    if df is None:
        try:
            df = pd.read_csv(raw_csv, encoding='utf-8', errors='replace')
        except Exception as e:
            sys.exit(f"Could not read CSV output: {e}")

    df.columns = df.columns.str.strip()

    # --- ANTIBODY (AK vs oAK) SUBTRACTION LOGIC ---
    df[['Antibody_Type', 'Pair_Key']] = df['Label'].apply(parse_ab_type_and_key)

    oak_df = df[df['Antibody_Type'] == 'oAK']
    oak_niod_lookup = oak_df.set_index('Pair_Key')['NIOD'].to_dict()
    oak_iod_lookup = oak_df.set_index('Pair_Key')['IOD'].to_dict()

    df['Matched_oAK_NIOD'] = df['Pair_Key'].map(oak_niod_lookup)
    df['Matched_oAK_IOD'] = df['Pair_Key'].map(oak_iod_lookup)

    def calc_delta_niod(row):
        if row['Antibody_Type'] == 'AK':
            if pd.notna(row['Matched_oAK_NIOD']):
                return row['NIOD'] - row['Matched_oAK_NIOD']
            return None
        elif row['Antibody_Type'] == 'oAK':
            return 0.0
        return None

    def calc_delta_iod(row):
        if row['Antibody_Type'] == 'AK':
            if pd.notna(row['Matched_oAK_IOD']):
                return row['IOD'] - row['Matched_oAK_IOD']
            return None
        elif row['Antibody_Type'] == 'oAK':
            return 0.0
        return None

    df['Delta_NIOD_AK_minus_oAK'] = df.apply(calc_delta_niod, axis=1)
    df['Delta_IOD_AK_minus_oAK'] = df.apply(calc_delta_iod, axis=1)

    df_export = df.drop(columns=['Pair_Key'])
    df_export.to_csv(final_csv, index=False, encoding='utf-8')

    if raw_csv.exists():
        raw_csv.unlink()

    print("\n================ FINAL BATCH RESULTS ================")
    print(f"Total processed images: {len(df_export)}")
    print(f"Results saved to: {final_csv}")
    print(f"Images without brain saved in: {image_dir / 'no_brain'}\n")

    for _, r in df_export.iterrows():
        status = r.get('Status', 'Processed')
        ab_type = r['Antibody_Type']
        
        if status == "No Brain":
            print(f"Image: {r['Label']:35s} | Type: {ab_type:3s} | Status: [NO BRAIN DETECTED]")
        elif ab_type == 'AK':
            delta_niod = r['Delta_NIOD_AK_minus_oAK']
            matched_oak = r['Matched_oAK_NIOD']
            if pd.notna(delta_niod):
                print(
                    f"Image: {r['Label']:35s} | Type: AK  | NIOD: {r['NIOD']:.6f} "
                    f"| oAK Baseline: {matched_oak:.6f} | Net NIOD (AK-oAK): {delta_niod:.6f}"
                )
            else:
                print(
                    f"Image: {r['Label']:35s} | Type: AK  | NIOD: {r['NIOD']:.6f} "
                    f"| [WARNING: Missing matching oAK control image!]"
                )
        elif ab_type == 'oAK':
            print(f"Image: {r['Label']:35s} | Type: oAK | Control Baseline NIOD: {r['NIOD']:.6f}")
        else:
            print(f"Image: {r['Label']:35s} | Type: Unknown | NIOD: {r['NIOD']:.6f}")


if __name__ == "__main__":
    imagej_exec, macro_path, image_dir, final_csv, sensitivity = select_files_interactive()
    run_imagej_batch(imagej_exec, macro_path, image_dir, final_csv, sensitivity)
    