"""Repository-root entry point; no training unless explicit authorized mode."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ml.cognitive.train import main
if __name__=='__main__':raise SystemExit(main())
