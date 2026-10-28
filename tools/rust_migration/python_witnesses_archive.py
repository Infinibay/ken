"""Portable Git authentication for the exact source snapshot used by host gates."""
from pathlib import Path,PurePosixPath
import base64,hashlib,subprocess

def object_id(kind,raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def tree_entries(raw):
    entries={};offset=0
    while offset<len(raw):
        end=raw.index(b'\0',offset);mode,name=raw[offset:end].split(b' ',1)
        digest=raw[end+1:end+21]
        if len(digest)!=20:raise ValueError('truncated Git tree')
        entries[name.decode()]=(mode.decode(),digest.hex());offset=end+21
    return entries

def git_proof(repo:Path,revision:str,sources):
    def read(kind,digest):return subprocess.check_output(['git','cat-file',kind,digest],cwd=repo)
    commit=read('commit',revision);root=commit.splitlines()[0].decode().removeprefix('tree ');trees={}
    for name in sources:
        current=root
        for part in PurePosixPath(name).parts[:-1]:
            if current not in trees:trees[current]=base64.b64encode(read('tree',current)).decode()
            current=tree_entries(base64.b64decode(trees[current]))[part][1]
        if current not in trees:trees[current]=base64.b64encode(read('tree',current)).decode()
    return dict(format='ken-source-git-proof/1',commit=revision,commit_bytes=base64.b64encode(commit).decode(),trees=trees,sources=sorted(sources))

def verify_git_proof(snapshot:Path,proof:dict,*,expected_commit=None,expected_sources=None):
    try:
        def require(ok,message):
            if not ok:raise ValueError(message)
        require(proof['format']=='ken-source-git-proof/1','Git proof format differs')
        commit=base64.b64decode(proof['commit_bytes'],validate=True)
        require(object_id('commit',commit)==proof['commit'],'Git commit differs')
        require(expected_commit is None or proof['commit']==expected_commit,'host Git revision differs')
        names=proof['sources'];require(names==sorted(set(names)),'Git source inventory differs')
        require(expected_sources is None or names==sorted(expected_sources),'host source inventory differs')
        trees={digest:base64.b64decode(raw,validate=True)for digest,raw in proof['trees'].items()}
        require(all(object_id('tree',raw)==digest for digest,raw in trees.items()),'Git tree differs')
        root=commit.splitlines()[0].decode().removeprefix('tree ')
        for name in names:
            path=PurePosixPath(name);require(not path.is_absolute()and path.parts and all(p not in('..','.')for p in path.parts),'unsafe source path')
            current=root
            for part in path.parts[:-1]:
                mode,current=tree_entries(trees[current])[part];require(mode=='40000','non-tree source ancestor')
            mode,digest=tree_entries(trees[current])[path.name];require(mode in('100644','100755'),'non-regular source')
            file=snapshot/name;require(not file.is_symlink()and file.resolve().is_relative_to(snapshot.resolve()),'source symlink escape')
            require(object_id('blob',file.read_bytes())==digest,'Git source bytes differ: '+name)
        return []
    except(OSError,ValueError,KeyError,TypeError,IndexError)as error:return[str(error)]
