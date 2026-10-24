"""Bounded regular-only source snapshots shared by native acceptance receipts."""
from __future__ import annotations
import hashlib,tarfile
from pathlib import Path,PurePosixPath
from .native_json import load

def read_source_snapshot(packet:Path,*,required:dict):
    def require(value,message):
        if not value:raise ValueError(message)
    records=load(packet/'SNAPSHOT.json');require(isinstance(records,dict)and 0<len(records)<=8192,'snapshot file count exceeds bound')
    for name,row in records.items():
        require(isinstance(name,str)and bool(name)and'\x00'not in name,'invalid snapshot member name')
        path=PurePosixPath(name);require(not path.is_absolute()and'..'not in path.parts and str(path)==name,'unsafe snapshot member path')
        require(set(row)=={'bytes','sha256'}and type(row['bytes'])is int and 0<=row['bytes']<=64*1024*1024,'invalid snapshot member bound')
    require(sum(row['bytes']for row in records.values())<=512*1024*1024,'snapshot exceeds512MiB')
    require(all(records.get(name)==row for name,row in required.items()),'source/tooling snapshot inputs differ')
    payloads={}
    with tarfile.open(packet/'source-snapshot.tar.gz','r:gz')as archive:
        for member in archive:
            require(member.isfile()and member.name in records and member.name not in payloads,'unsafe,duplicated or unexpected snapshot member')
            row=records[member.name];require(member.size==row['bytes'],'snapshot member size differs')
            stream=archive.extractfile(member);require(stream is not None,'snapshot member missing')
            raw=stream.read(row['bytes']+1)
            require(len(raw)==row['bytes']and hashlib.sha256(raw).hexdigest()==row['sha256'],'snapshot payload differs')
            payloads[member.name]=raw
    require(payloads.keys()==records.keys(),'snapshot inventory differs')
    return payloads

def extract_source_snapshot(packet:Path,destination:Path,*,required:dict):
    if destination.exists()or destination.is_symlink():raise ValueError('snapshot destination already exists')
    payloads=read_source_snapshot(packet,required=required)
    destination.mkdir(parents=True)
    for name,raw in payloads.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    return destination
