"""Windows current-user DPAPI for the dedicated Chaoxing session."""
import ctypes,os
from ctypes import wintypes

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _transform(data,decrypt=False):
    if os.name!='nt': raise OSError('Windows DPAPI required')
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    entropy_buffer=ctypes.create_string_buffer(b'courseinbox-chaoxing-session-v1');entropy=Blob(len(entropy_buffer.raw)-1,ctypes.cast(entropy_buffer,ctypes.POINTER(ctypes.c_ubyte)))
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    if decrypt: ok=crypt.CryptUnprotectData(ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(target))
    else: ok=crypt.CryptProtectData(ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(target))
    if not ok: raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data,target.size)
    finally:
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p;kernel.LocalFree(target.data)

def seal(data):return _transform(data)
def unseal(data):return _transform(data,True)
