"""Build once; validate fresh runtime-only wheel, sdist and actual bridge image installs."""

import email
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ENV = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT") if key in os.environ}
ENV.update({"PYTHONNOUSERSITE": "1", "COMPOSE_ENV_FILES": os.devnull})
SOURCE_MARKER = ".repository-source"
STALE_NOTICE = b"Synthetic stale generated notice; the repository notice must replace this.\n"
UNRELATED_NOTICE = b"Synthetic unrelated parent notice; distributions must ignore this.\n"


def run(command, cwd, timeout=300, check=True):
    print("RUN " + " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), cwd=cwd, env=ENV, timeout=timeout,
                          check=check, text=True, capture_output=True)


def archive_check(path, expected_notice, app_files):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            content = {n: archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        metadata_name = next(n for n in content if n.endswith('.dist-info/METADATA'))
        notice_name = metadata_name.replace('METADATA', 'licenses/LICENSE')
        allowed = {metadata_name.rsplit('/', 1)[0] + '/' + n for n in
                   ('METADATA', 'WHEEL', 'top_level.txt', 'RECORD', 'licenses/LICENSE')}
    else:
        with tarfile.open(path) as archive:
            content = {m.name.split('/', 1)[1]: archive.extractfile(m).read()
                       for m in archive.getmembers() if m.isfile()}
        metadata_name, notice_name = 'PKG-INFO', 'LICENSE'
        allowed = {'PKG-INFO', 'LICENSE', 'pyproject.toml', 'setup.py', 'setup.cfg', 'MANIFEST.in'} | {
            'finary_bridge.egg-info/' + n for n in
            ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'requires.txt', 'top_level.txt')}
    assert set(content) <= set(app_files) | allowed, (
        "Unexpected archive files: " + repr(sorted(set(content) - set(app_files) - allowed))
    )
    assert set(app_files) <= set(content), "Application files missing from archive"
    for name, expected in app_files.items():
        assert content[name] == expected, "Archive application/resource parity failed: " + name
    metadata = email.message_from_bytes(content[metadata_name])
    assert metadata['License-Expression'] == 'MIT', "Archive missing MIT metadata"
    assert metadata.get_all('License-File') == ['LICENSE'], "Archive missing notice metadata"
    assert content[notice_name] == expected_notice, "Archive notice mismatch"
    assert metadata['Version'] == '1.0.0'
    print(json.dumps({"archive": path.name, "inventory": sorted(content)}), flush=True)


def extract_sdist(sdist, destination):
    destination.mkdir(exist_ok=True)
    with tarfile.open(sdist) as archive:
        archive.extractall(destination, filter="data")
    extracted = [path for path in destination.iterdir() if path.is_dir()]
    assert len(extracted) == 1, "Source distribution must have one top-level directory"
    return extracted[0]


def rejected_build(build_python, package, output, expected):
    output.mkdir()
    result = run([build_python, '-I', '-m', 'build', '--no-isolation', '--wheel',
                  '--outdir', output, package], package.parent, check=False)
    assert result.returncode != 0, "Incomplete source unexpectedly produced a wheel"
    assert expected in result.stdout + result.stderr, "Build did not report the missing notice"
    assert not list(output.iterdir()), "Rejected build left a misleading artifact"


def validate_sdist_rebuilds(build_python, sdist, work, expected_notice, app_files):
    for name, parent_notice in (("no-parent", None), ("competing-parent", UNRELATED_NOTICE)):
        parent = work / ("sdist-rebuild-" + name)
        parent.mkdir()
        if parent_notice is not None:
            (parent / 'LICENSE').write_bytes(parent_notice)
        package = extract_sdist(sdist, parent)
        notice = package / 'LICENSE'
        assert notice.read_bytes() == expected_notice, "Extracted sdist notice mismatch"
        artifacts = work / ("sdist-rebuilt-artifacts-" + name)
        artifacts.mkdir()
        run([build_python, '-I', '-m', 'build', '--no-isolation', '--wheel',
             '--outdir', artifacts, package], work)
        wheel, = artifacts.glob('*.whl')
        archive_check(wheel, expected_notice, app_files)
        assert notice.read_bytes() == expected_notice, "Rebuild replaced the bundled notice"
        with zipfile.ZipFile(wheel) as archive:
            assert UNRELATED_NOTICE not in archive.read(next(
                name for name in archive.namelist() if name.endswith('.dist-info/licenses/LICENSE')
            )), "Rebuilt wheel contains the unrelated parent notice"
        print("SDIST_REBUILD_" + name.replace('-', '_').upper() + "_VALIDATED", flush=True)

    parent = work / 'sdist-rebuild-incomplete'
    parent.mkdir()
    (parent / 'LICENSE').write_bytes(UNRELATED_NOTICE)
    package = extract_sdist(sdist, parent)
    (package / 'LICENSE').unlink()
    rejected_build(build_python, package, work / 'sdist-rebuild-incomplete-artifacts',
                   "Complete source distribution requires its bundled LICENSE")
    print("SDIST_INCOMPLETE_NOTICE_REJECTED", flush=True)


def negative_controls(python, site, fixture, outside):
    command = [python, '-I', fixture / 'smoke.py', '--reference', fixture]

    def rejected(expected, override=None):
        result = run(override or command, outside, timeout=45, check=False)
        assert result.returncode != 0 and expected in result.stderr, result.stdout + result.stderr
        print('NEGATIVE_CONTROL_VALIDATED: ' + expected, flush=True)

    metadata = next(site.glob('finary_bridge-*.dist-info/METADATA'))
    mutations = [
        (site / 'app/mcp-contract.json', None, 'Missing packaged contract resource'),
        (site / 'app/workbook-schema.json', None, 'Missing packaged contract resource'),
        (metadata, metadata.read_bytes().replace(b'License-Expression: MIT\n', b''),
         'Missing MIT license metadata'),
        (metadata.parent / 'licenses/LICENSE', None, 'Missing installed license notice'),
    ]
    for path, replacement, expected in mutations:
        original = path.read_bytes()
        try:
            if replacement is None:
                path.unlink()
            else:
                path.write_bytes(replacement)
            rejected(expected)
        finally:
            path.write_bytes(original)
    # An otherwise valid app on sys.path must not conceal a missing installed app.
    checkout = outside / 'checkout'
    checkout.mkdir()
    application = site / 'app'
    shutil.move(application, checkout / 'app')
    try:
        code = ("import runpy,sys; sys.path.insert(0, " + repr(str(checkout)) + "); "
                "sys.argv=" + repr([str(fixture / 'smoke.py'), '--reference', str(fixture)])
                + "; runpy.run_path(sys.argv[0], run_name='__main__')")
        rejected('Application import outside intended installation', [python, '-I', '-c', code])
    finally:
        shutil.move(checkout / 'app', application)
    run(command, outside, timeout=90)
    print('RESTORED_INSTALLATION_VALIDATED', flush=True)


def validate(work):
    source = work / 'source'
    package = source / 'finary-bridge'
    package.mkdir(parents=True)
    shutil.copyfile(ROOT / 'LICENSE', source / 'LICENSE')
    expected_notice = (ROOT / 'LICENSE').read_bytes()
    # Include tracked package-side tests/support in the clean source tree so the
    # archive inventory check detects accidental discovery of non-product files.
    tracked = run(['git', 'ls-files', '-z', '--', 'finary-bridge'], ROOT).stdout
    for name in filter(None, tracked.split('\0')):
        relative = Path(name).relative_to('finary-bridge')
        destination = package / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    for name in ('pyproject.toml', 'setup.py', 'MANIFEST.in', SOURCE_MARKER):
        shutil.copyfile(ROOT / 'finary-bridge' / name, package / name)
    assert (package / SOURCE_MARKER).is_file(), "Source layout marker missing from staging"
    (package / 'LICENSE').write_bytes(STALE_NOTICE)
    app_files = {}
    for path in sorted((ROOT / 'finary-bridge/app').rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.json'):
            relative = path.relative_to(ROOT / 'finary-bridge')
            app_files[str(relative)] = path.read_bytes()
            destination = package / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    fixture = work / 'fixture'
    fixture.mkdir()
    shutil.copyfile(ROOT / 'scripts/smoke-installed-product.py', fixture / 'smoke.py')
    for name, src in [('LICENSE', ROOT / 'LICENSE'),
                      ('finary-mcp-contract.json', ROOT / 'docs/finary-mcp-contract.json'),
                      ('google-sheets-schema.json', ROOT / 'docs/google-sheets-schema.json')]:
        shutil.copyfile(src, fixture / name)
    for packaged, canonical in [('mcp-contract.json', 'finary-mcp-contract.json'),
                                ('workbook-schema.json', 'google-sheets-schema.json')]:
        assert app_files['app/' + packaged] == (fixture / canonical).read_bytes()
    artifacts = work / 'artifacts'
    artifacts.mkdir()
    # Exercise the declared backend minimum, independently of the outer dev environment.
    builder = work / 'builder'
    run([sys.executable, '-I', '-m', 'venv', builder], work)
    build_python = builder / 'bin/python'
    run([build_python, '-I', '-m', 'pip', '--isolated', 'install', '--no-cache-dir',
         'build>=1.2,<2', 'setuptools==77.0.3', 'wheel'], work)
    missing_source = work / 'missing-source'
    missing_package = missing_source / 'finary-bridge'
    shutil.copytree(package, missing_package)
    rejected_build(build_python, missing_package, work / 'missing-source-artifacts',
                   "Repository source build requires the authoritative root LICENSE")
    print('SOURCE_MISSING_NOTICE_REJECTED', flush=True)
    run([build_python, '-I', '-m', 'build', '--no-isolation', '--outdir', artifacts, package], work)
    wheel, = artifacts.glob('*.whl')
    sdist, = artifacts.glob('*.tar.gz')
    for artifact in (wheel, sdist):
        archive_check(artifact, expected_notice, app_files)
    assert (package / 'LICENSE').read_bytes() == expected_notice
    print('SOURCE_STALE_NOTICE_REFRESH_VALIDATED', flush=True)
    # Make the original staging tree unavailable before the sdist builds its own wheel.
    shutil.rmtree(source)
    validate_sdist_rebuilds(build_python, sdist, work, expected_notice, app_files)
    print('SDIST_ORIGIN_REMOVED_VALIDATED', flush=True)
    for kind, artifact in [('wheel', wheel), ('sdist', sdist)]:
        installation = work / kind
        run([sys.executable, '-I', '-m', 'venv', installation], work)
        python = installation / 'bin/python'
        run([python, '-I', '-m', 'pip', '--isolated', 'install', '--no-cache-dir', artifact], work)
        run([python, '-I', '-m', 'pip', 'check'], work)
        outside = work / (kind + '-outside')
        outside.mkdir()
        result = run([python, '-I', fixture / 'smoke.py', '--reference', fixture,
                      '--prefix', installation], outside, timeout=90)
        print(result.stdout, flush=True)
        print(kind.upper() + '_VALIDATED', flush=True)
        if kind == 'wheel':
            site = Path(run([python, '-I', '-c',
                             "import sysconfig; print(sysconfig.get_path('purelib'))"], work).stdout.strip())
            negative_controls(python, site, fixture, outside)
    # Docker is required: no skip flag and no success result when unavailable.
    run(['docker', 'info'], work, timeout=30)
    config = json.loads(run(['docker', 'compose', '--env-file', os.devnull,
                             '-f', ROOT / 'docker-compose.yml', 'config', '--format', 'json'],
                            work).stdout)
    build = config['services']['finary-bridge']['build']
    image = 'finary-artifact-' + uuid4().hex + ':test'
    container = 'finary-artifact-' + uuid4().hex
    try:
        run(['docker', 'build', '-t', image, '-f',
             Path(build['context']) / build.get('dockerfile', 'Dockerfile'), build['context']],
            work, timeout=600)
        result = run(['docker', 'run', '--rm', '--name', container, '--network', 'none',
                      '--workdir', '/tmp', '--mount', f'type=bind,source={fixture},target=/smoke,readonly',
                      image, 'python', '-I', '/smoke/smoke.py', '--reference', '/smoke',
                      '--prefix', '/usr/local'], work, timeout=120)
        print(result.stdout, flush=True)
        run(['docker', 'run', '-d', '--name', container, '--network', 'none',
             '-e', 'FINARY_BRIDGE_API_KEY=synthetic-image-key',
             '-e', 'FINARY_MCP_STATE_PATH=/tmp/forbidden-state/oauth.json',
             '--mount', f'type=bind,source={fixture},target=/smoke,readonly', image], work)
        result = run(['docker', 'exec', container, 'python', '-I', '/smoke/smoke.py',
                      '--normal-health'], work, timeout=45)
        print(result.stdout, flush=True)
        print('IMAGE_VALIDATED', flush=True)
    finally:
        run(['docker', 'rm', '-f', container], work, check=False)
        run(['docker', 'image', 'rm', '-f', image], work, check=False)


if __name__ == '__main__':
    try:
        with tempfile.TemporaryDirectory(prefix='finary-artifacts-') as directory:
            validate(Path(directory).resolve())
    except subprocess.CalledProcessError as error:
        print(error.stdout or '', file=sys.stderr)
        print(error.stderr or '', file=sys.stderr)
        raise SystemExit('Required release artifact gate failed') from None
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise SystemExit('Required release artifact environment unavailable: ' + str(error)) from None
    print('RELEASE_ARTIFACTS_VALIDATED')
