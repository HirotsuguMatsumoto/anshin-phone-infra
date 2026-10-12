"""Generate an 8000 Hz PCMU tone; no human voice or external media."""
import audioop
import math
from pathlib import Path
import struct
pcm = b"".join(struct.pack("<h",int(8000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(8000))
Path("/mock-fax/synthetic-audio.ulaw").write_bytes(audioop.lin2ulaw(pcm,2))
