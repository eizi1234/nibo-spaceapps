"""Copy the reviewed, output-free sleep notebook to a private location."""
import argparse
from pathlib import Path
import shutil

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    source = Path(__file__).resolve().parents[1] / "notebooks/sleep_prediction_clean.ipynb"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, args.output)

if __name__ == "__main__":
    main()
