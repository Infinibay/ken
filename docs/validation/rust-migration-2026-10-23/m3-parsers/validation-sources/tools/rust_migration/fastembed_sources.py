"""Per-model owned CI acquisition; borrowed offline snapshots stay untouched."""
from __future__ import annotations

import argparse
from contextlib import contextmanager,ExitStack
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.parse
import urllib.request

from .preparation import PreparedNativeFastEmbed,FASTEMBED_ENV,fastembed_environment

EVIDENCE_HEADROOM=512*1024**2
BUILD_HEADROOM=3*1024**3


def check_capacity(root:Path,needed:int)->dict:
    usage=shutil.disk_usage(root)
    if usage.free<needed:
        raise OSError(f'FastEmbed capacity: need {needed} free bytes, have {usage.free}; '
            'use an adequately provisioned workspace; no unrelated files were removed')
    return {'required_free_bytes':needed,'observed_free_bytes':usage.free,'total_bytes':usage.total}


def capacity_plan(catalogue:dict)->dict:
    from .fastembed_ownership import MODELS
    def row(definition,copies):
        size=sum(r['bytes']for r in definition['assets']['artifacts'].values())
        return {'model':definition['name'],'source_bytes':size,'copies':copies,
            'required_free_bytes':size*copies+EVIDENCE_HEADROOM}
    parity=[row(m,2)for m in catalogue['models']]
    ownership=[row(next(m for m in catalogue['models']if m['name']==name),3)for name in MODELS]
    held=sum(r['source_bytes']for r in ownership)
    extra=2*max(r['source_bytes']for r in ownership)
    suite={'models':MODELS,'source_bytes':held,'additional_private_bytes':extra,
        'required_free_bytes':held+extra+EVIDENCE_HEADROOM}
    return {'parity':parity,'ownership':ownership,
        'process_tests':suite,
        'peak_bytes':max(suite['required_free_bytes'],*(r['required_free_bytes']for r in parity+ownership)),
        'evidence_headroom_bytes':EVIDENCE_HEADROOM,'build_headroom_bytes':BUILD_HEADROOM}


def _download(assets,snapshot):
    for artifact in assets.artifacts:
        target=snapshot/artifact.path;target.parent.mkdir(parents=True,exist_ok=True)
        url=(f'https://huggingface.co/{assets.model_id}/resolve/{assets.revision}/'
            +urllib.parse.quote(artifact.path,safe='/'))
        digest=hashlib.sha256();size=0
        with urllib.request.urlopen(url,timeout=60)as source,target.open('xb')as output:
            while chunk:=source.read(min(65536,artifact.bytes-size+1)):
                size+=len(chunk)
                if size>artifact.bytes:raise ValueError(f'oversized registered artifact: {artifact.path}')
                output.write(chunk);digest.update(chunk)
        if size!=artifact.bytes or digest.hexdigest()!=artifact.sha256:
            raise ValueError(f'registered artifact bytes/hash mismatch: {artifact.path}')


@contextmanager
def source_lease(prepared:PreparedNativeFastEmbed,definition:dict,*,copies:int):
    """Keep one verified model until its consumer and private owners have closed."""
    if not prepared.acquire:
        yield prepared
        return
    from ken.model_assets import ModelAssets
    assets=ModelAssets.from_dict(definition['assets'])
    if copies not in (2,3):raise ValueError('source/private-owner copy count required')
    prepared.sources.mkdir(parents=True,exist_ok=True)
    check_capacity(prepared.sources,sum(a.bytes for a in assets.artifacts)*copies+EVIDENCE_HEADROOM)
    with tempfile.TemporaryDirectory(prefix='lease-',dir=prepared.sources)as temporary:
        root=Path(temporary);snapshot=root/assets.model_id.replace('/','--')/assets.revision
        snapshot.mkdir(parents=True)
        _download(assets,snapshot)
        yield replace(prepared,sources=root,acquire=False)


@contextmanager
def suite_source_lease(prepared:PreparedNativeFastEmbed|None,*,environ:dict[str,str]):
    """Hold the five real process-test inputs before their execution clock starts."""
    values=fastembed_environment(prepared,environ=environ)
    if not values:
        yield None
        return
    effective=PreparedNativeFastEmbed(*(Path(values[k])for k in FASTEMBED_ENV),
        acquire=values.get('KEN_FASTEMBED_ACQUIRE')=='1')
    if not effective.acquire:
        yield effective
        return
    from .fastembed_ownership import MODELS
    catalogue=json.loads(effective.registry.read_bytes())
    effective.sources.mkdir(parents=True,exist_ok=True)
    check_capacity(effective.sources,capacity_plan(catalogue)['process_tests']['required_free_bytes'])
    with ExitStack()as owners:
        root=Path(owners.enter_context(tempfile.TemporaryDirectory(prefix='test-sources-',dir=effective.sources)))
        for name in MODELS:
            definition=next(m for m in catalogue['models']if m['name']==name)
            acquired=owners.enter_context(source_lease(effective,definition,copies=3))
            assets=definition['assets'];relative=Path(assets['model_id'].replace('/','--'))/assets['revision']
            destination=root/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            destination.symlink_to(acquired.sources/relative,target_is_directory=True)
        yield replace(effective,sources=root,acquire=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True)
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--before-build',action='store_true')
    args=parser.parse_args();args.sources.mkdir(parents=True,exist_ok=True)
    plan=capacity_plan(json.loads(args.registry.read_bytes()))
    measured=check_capacity(args.sources,plan['peak_bytes']+(BUILD_HEADROOM if args.before_build else 0))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({'plan':plan,'capacity':measured},indent=2)+'\n')
    print(json.dumps(measured))


if __name__=='__main__':main()
