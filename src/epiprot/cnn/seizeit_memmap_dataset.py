"""125 hasta için bellek dostu memmap veri yönetimi."""
import numpy as np
from pathlib import Path
from typing import List, Tuple

def save_to_memmap(X_list: List[np.ndarray], y_list: List[np.ndarray], out_dir: Path) -> Tuple[Path, Path]:
    """Verileri diske memmap olarak kaydet."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    total_samples = sum(len(y) for y in y_list)
    channels = X_list[0].shape[1]
    freq = X_list[0].shape[2]
    time = X_list[0].shape[3]
    
    X_path = out_dir / "X_all.npy"
    y_path = out_dir / "y_all.npy"
    
    X_mm = np.lib.format.open_memmap(X_path, mode='w+', dtype=np.float32, 
                                     shape=(total_samples, channels, freq, time))
    y_mm = np.lib.format.open_memmap(y_path, mode='w+', dtype=np.float32, 
                                     shape=(total_samples,))
    
    offset = 0
    for X, y in zip(X_list, y_list):
        n = len(y)
        X_mm[offset:offset+n] = X
        y_mm[offset:offset+n] = y
        offset += n
        
    X_mm.flush()
    y_mm.flush()
    return X_path, y_path