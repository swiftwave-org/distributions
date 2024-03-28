import os
import re
import shutil
import subprocess
import pexpect


def create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)

def delete_folder(path):
    if os.path.exists(path):
        shutil.rmtree(path)

def clean_folder(path):
    delete_folder(path)
    create_folder(path)

def import_key() -> str:
    result = subprocess.run(
        ["gpg", "--import", "pgp-key.private"], stderr=subprocess.PIPE
    )
    match = re.search(r"key\s(\w+):", result.stderr.decode("utf-8"), re.MULTILINE)
    if match:
        key_id = match.group(1)
        return key_id
    else:
        raise Exception("Key ID not found")

def delete_key(key_id: str):
    # stdin buffer with "Y" to confirm deletion
    p = pexpect.spawn('gpg --yes --delete-secret-keys ' + key_id)
    p.expect('Delete this key from the keyring?')
    p.sendline('y')
    p.expect('This is a secret key! - really delete?')
    p.sendline('y')
    p.expect(pexpect.EOF)
    p = pexpect.spawn('gpg --yes --delete-keys ' + key_id)
    p.expect('Delete this key from the keyring?')
    p.sendline('y')
    p.expect(pexpect.EOF)

def do_hash(hash_name, hash_cmd, start_paths=[]):
    output = f"{hash_name}:\n"
    for start_path in start_paths:
        for root, dirs, files in os.walk(start_path):
            for filename in files:
                filepath = os.path.join(root, filename)
                if filename == "Release":
                    continue
                hash_output = subprocess.check_output([hash_cmd, filepath]).decode().split()[0]
                file_size = os.path.getsize(filepath)
                file_absolute_path = filepath.removeprefix(start_path)
                output += f" {hash_output} {file_size} {file_absolute_path}\n"
    return output

def process_rpm_repo(base_path, key_id, base_url):
    clean_folder(base_path)
    create_folder(f"{base_path}/rpms")
    create_folder(f"{base_path}/repodata")

    rpm_files = [f for f in os.listdir("builds") if f.endswith(".rpm")]
    package_names = set()
    for f in rpm_files:
        sf = f.rsplit(".", 2)
        arch = sf[1]
        package_name = sf[0].rsplit("-", 2)[0]
        package_names.add(package_name)
        create_folder(f"{base_path}/rpms/{arch}")
        shutil.copy(f"builds/{f}", f"{base_path}/rpms/{arch}/{f}")
        # sign the rpm
        r = subprocess.run(
            [
                "rpm",
                "--addsign",
                "--define",
                "%__gpg /usr/bin/gpg",
                "--define",
                f"%_gpg_name {key_id}",
                f"{base_path}/rpms/{arch}/{f}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if r.returncode != 0:
            raise Exception(f'rpm sign failed: {r.stderr.decode("utf-8")}')

    # run createrepo
    r = subprocess.run(
        ["createrepo_c", base_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if r.returncode != 0:
        raise Exception(f'createrepo failed: {r.stderr.decode("utf-8")}')

    # sign the repomd.xml
    r = subprocess.run(
        ["gpg", "--default-key", key_id, "--detach-sign", "--armor", f"{base_path}/repodata/repomd.xml"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if r.returncode != 0:
        raise Exception(f'repomd.xml sign failed: {r.stderr.decode("utf-8")}')
    
    # create repo file
    with open(f"{base_path}/swiftwave.repo", "w") as f:
        for package_name in package_names:
            f.write(f'''[{package_name}]
name=Swiftwave Repository
baseurl={base_url}
enabled=1
gpgcheck=1
gpgkey={base_url}pgp-key.public
''')

    # copy the public key
    shutil.copy("pgp-key.public", f"{base_path}/pgp-key.public")
    # copy the rpm.html file
    shutil.copy("pages/rpm.html", f"{base_path}/index.html")

def process_deb_repo(base_path, key_id):
    clean_folder(base_path)
    create_folder(f"{base_path}/dists")
    create_folder(f"{base_path}/pool")
    create_folder(f"{base_path}/pool/stable")

    deb_files = [f for f in os.listdir("builds") if f.endswith(".deb")]
    aarchs = ["amd64", "arm64", "i386"]
    package_names = set()
    package_name_arch = dict()
    # process deb files
    for f in deb_files:
        sf = f.rsplit("_", 2)
        arch = sf[2].rsplit(".", 1)[0].strip()
        package_name = sf[0]
        create_folder(f"{base_path}/pool/stable/{package_name}")
        shutil.copy(f"builds/{f}", f"{base_path}/pool/stable/{package_name}/{f}")
        create_folder(f"{base_path}/dists/{package_name}/stable")
        package_names.add(package_name)
        if package_name not in package_name_arch:
            package_name_arch[package_name] = set()
        package_name_arch[package_name].add(arch)


    # create Packages & Packages.gz
    for package_name in package_names:
        for arch in aarchs:
            # check if any debian package is available for this arch
            if arch not in package_name_arch.get(package_name, set()):
                continue
            create_folder(f"{base_path}/dists/{package_name}/stable/binary-{arch}")
            r = subprocess.run(
                [
                    "dpkg-scanpackages",
                    "--multiversion",
                    "--arch",
                    arch,
                    f"pool/stable/{package_name}",
                    "/dev/null",
                ],
                cwd=base_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if r.returncode != 0:
                raise Exception(f'dpkg-scanpackages failed: {r.stderr.decode("utf-8")}')
            packages = r.stdout.decode("utf-8")
            with open(f"{base_path}/dists/{package_name}/stable/binary-{arch}/Packages", "w") as f:
                f.write(packages)
            r = subprocess.run(
                ["gzip", "-c", f"{base_path}/dists/{package_name}/stable/binary-{arch}/Packages"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if r.returncode != 0:
                raise Exception(f'gzip failed: {r.stderr.decode("utf-8")}')
            with open(f"{base_path}/dists/{package_name}/stable/binary-{arch}/Packages.gz", "wb") as f:
                f.write(r.stdout)
    
    # create Release file
    for package_name in package_names:
        with open(f"{base_path}/dists/{package_name}/Release", "w") as f:
            f.write(f'''Origin: Swiftwave Repository
Suite: stable
Codename: {package_name}
Architectures: {' '.join(aarchs)}
Components: main
Date: {subprocess.run(["date", "-Ru"], stdout=subprocess.PIPE).stdout.decode("utf-8")}''')
            # generate MD5 and SHA1 SHA256 SHA512 hashes
            paths = [f"{base_path}/dists/{package_name}/"]
            f.write(do_hash("MD5Sum", "md5sum", paths))
            f.write(do_hash("SHA1", "sha1sum", paths))
            f.write(do_hash("SHA256", "sha256sum", paths))
            f.write(do_hash("SHA512", "sha512sum", paths))
    
        # sign the Release file
        r = subprocess.run(
            ["gpg", "--default-key", key_id, "-abs", "--output",  f"{base_path}/dists/{package_name}/Release.gpg", f"{base_path}/dists/{package_name}/Release"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if r.returncode != 0:
            raise Exception(f'Release sign failed: {r.stderr.decode("utf-8")}')

        # generate InRelease
        r = subprocess.run(
            ["gpg", "--default-key", key_id, "--clearsign", "--output", f"{base_path}/dists/{package_name}/InRelease", f"{base_path}/dists/{package_name}/Release"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if r.returncode != 0:
            raise Exception(f'InRelease sign failed: {r.stderr.decode("utf-8")}')
    
    # copy the public key
    shutil.copy("pgp-key.public", f"{base_path}/pgp-key.public")
    # copy the deb.html file
    shutil.copy("pages/deb.html", f"{base_path}/index.html")

def process_repo(base_url, log):
    key_id = import_key()
    try:
        clean_folder("builds")
        clean_folder("repo")
        for f in os.listdir("source"):
            shutil.copy(f"source/{f}", f"builds/{f}")
        process_rpm_repo('repo/rpm', key_id, base_url)
        log("RPM repo created")
        process_deb_repo("repo/deb", key_id)
        log("DEB repo created")
        # copy index.html to repo
        shutil.copy("pages/index.html", "repo/index.html")
        # delete the /var/www/html/ folder
        subprocess.run(["rm", "-rf", "/var/www/html"])
        log("Deleted /var/www/html/ folder")
        # move all the contents of `repo` folder to `/usr/share/nginx/html/` folder
        subprocess.run(["mv", "-f", "repo", "/var/www/html"])
        log("Moved repo to /var/www/html/")
    except Exception as e:
        log(e)
        log("Failed to create repo")
    finally:
        delete_key(key_id)
        delete_folder("builds")