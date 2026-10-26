import zipfile
import os
from pathlib import Path

def package():
    base_dir = Path(__file__).resolve().parent.parent
    output_zip = base_dir / "static" / "aicte-complaint-monitoring.zip"
    exclude_dirs = {"venv", "__pycache__", ".pytest_cache", ".git"}
    
    count = 0
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(base_dir):
            dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
            for f in filenames:
                if f.endswith((".pyc", ".pyo")) or f.endswith(".log") or f.endswith(".zip"):
                    continue
                full_path = Path(dirpath) / f
                arcname = full_path.relative_to(base_dir)
                zf.write(full_path, arcname)
                count += 1
                
    print(f"Clean archive packaged with {count} files to: {output_zip}")

if __name__ == "__main__":
    package()
