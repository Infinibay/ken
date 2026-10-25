"""Check native code headers against one registered OS/architecture target."""
from pathlib import Path
import struct
from .native_platform import native_target

def check_native_architecture(path:Path,target:tuple[str,str])->None:
    system,arch=native_target(*target)
    with path.open('rb')as stream:header=stream.read(32)
    if system=='linux':
        if header[:6]!=b'\x7fELF\x02\x01'or len(header)<20:raise ValueError('native64bit Linux binary required')
        if struct.unpack('<H',header[18:20])[0]!={'x86_64':62,'aarch64':183}[arch]:raise ValueError('native binary architecture differs')
    elif header[:4]!=b'\xcf\xfa\xed\xfe'or len(header)<8 or struct.unpack('<I',header[4:8])[0]!=0x0100000c:
        raise ValueError('native arm64 macOS binary required')
