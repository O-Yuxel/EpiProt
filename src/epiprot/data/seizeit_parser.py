"""SeizeIT2 (BIDS formatı) etiket dosyalarını (.tsv) ayrıştırır."""
from __future__ import annotations
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

@dataclass
class SeizeitAnnotation:
    tsv_path: str
    seizures: List[tuple[float, float]] = field(default_factory=list)
    recording_duration: float = 0.0
    has_seizure: bool = False

def parse_seizeit_tsv(tsv_path: Path) -> SeizeitAnnotation:
    """Bir .tsv dosyasını okur ve nöbet (sz) aralıklarını bulur."""
    result = SeizeitAnnotation(tsv_path=str(tsv_path))
    
    try:
        df = pd.read_csv(tsv_path, sep='\t')
    except Exception:
        return result
        
    if df.empty:
        return result
        
    # Toplam süreyi al
    if 'recordingDuration' in df.columns and len(df) > 0:
        result.recording_duration = float(df['recordingDuration'].iloc[0])
        
    # eventType sütununda 'sz' ile başlayanları (sz_foc, sz_gen, vs.) filtrele
    # 'impd' (impedans) veya 'bckg' (arka plan) etiketlerini dışarıda bırakır
    sz_mask = df['eventType'].str.lower().str.startswith('sz')
    sz_df = df[sz_mask]
    
    if not sz_df.empty:
        result.has_seizure = True
        for _, row in sz_df.iterrows():
            onset = float(row['onset'])
            duration = float(row['duration'])
            result.seizures.append((onset, onset + duration))
            
    return result