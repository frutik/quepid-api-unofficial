"""Getting a dataset's files, from GitHub the first time and the cache after.

``load_dataset`` takes a dataset name and nothing about where its files are, so
this is what makes that true. Downloads land under ``TMP_DIR`` -- which the app
image sets to ``/tmp/app``, 0777 and declared as a ``VOLUME``, so a 51 MB parquet
is fetched once and not once per ``docker compose run``.

The two GitHub URL forms are **not** interchangeable, which is why each dataset
spells its own out:

- ``raw.githubusercontent.com/<repo>/<ref>/<path>`` serves a file's bytes -- but
  for a repository using Git LFS it serves the pointer file instead, 133 bytes
  of text where a parquet was expected. esci-data is such a repository.
- ``github.com/<repo>/raw/<ref>/<path>`` resolves LFS and redirects to the real
  object.

The guard below catches a pointer anyway: cached, it would fail much later and
much less clearly, as a corrupt dataset.
"""
import os
import tempfile
from pathlib import Path

import requests

CACHE_DIR = 'quepid-datasets'
CHUNK = 1 << 20  # 1 MiB
# Progress is reported every this many bytes, so a 51 MB download says something
# four times and a 20 KB one says nothing.
REPORT_EVERY = 16 << 20
LFS_POINTER = b'version https://git-lfs.github.com/spec/v1'


class FetchError(Exception):
    """A dataset file could not be obtained."""


def cache_dir(dataset):
    """Where this dataset's files live, downloaded or not."""
    root = os.getenv('TMP_DIR') or tempfile.gettempdir()
    return Path(root) / CACHE_DIR / dataset.name


def ensure(dataset, report):
    """The directory holding this dataset's files, fetching what is missing."""
    directory = cache_dir(dataset)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FetchError(f'Cannot use {directory} for downloads: {e}')

    for name, url in dataset.files.items():
        path = directory / name
        # Size, not just existence: a zero-byte file is a failed download that
        # somehow got past the rename below.
        if path.is_file() and path.stat().st_size:
            continue
        report(f'Downloading {name} from {url}')
        _download(url, path, report)

    return directory


def _download(url, path, report):
    """Stream one file into place, atomically."""
    # Written beside the target and renamed at the end, so an interrupted
    # download is never mistaken for a cached file by the next run.
    part = path.with_name(path.name + '.part')
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            # Content-Length counts the bytes on the wire, and requests hands
            # back decoded ones: GitHub gzips the WANDS CSVs, so 19942 bytes
            # arrive against a declared 8063. Only compare when nothing was
            # encoded, which is the case for the ESCI parquet.
            total = int(response.headers.get('content-length') or 0)
            verifiable = total and 'content-encoding' not in response.headers
            done = 0
            reported = 0

            with part.open('wb') as handle:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if not done and chunk.startswith(LFS_POINTER):
                        raise FetchError(
                            f'{url} served a Git LFS pointer, not the file. That URL has to be '
                            f'the github.com/<repo>/raw/<ref>/<path> form for an LFS repository.'
                        )
                    handle.write(chunk)
                    done += len(chunk)

                    if done - reported >= REPORT_EVERY:
                        reported = done
                        report(f'  {done >> 20} MiB' + (f' of {total >> 20} MiB' if total else ''))

        if verifiable and done != total:
            raise FetchError(f'{url} sent {done} bytes of {total}.')
        part.replace(path)
    except requests.RequestException as e:
        raise FetchError(f'Downloading {url} failed: {e}')
    except OSError as e:
        raise FetchError(f'Writing {path} failed: {e}')
    finally:
        # A no-op once replace() has moved it; cleanup on every failure path.
        part.unlink(missing_ok=True)
