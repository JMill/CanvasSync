# worklog. last edit 2025-08-30 by jmill
# - fix AES key derivation to handle bytes/str consistently. ensure bcrypt hash bytes written to file as bytes.
# - add proper PKCS#7 unpadding on decrypt to avoid stray control bytes corrupting settings parsing.

"""
CanvasSync by Mathias Perslev
February 2017

--------------------------------------------

cryptography.py, module

Functions used to encrypt and decrypt the settings stored in the .CanvasSync.settings file. When the user has specified
settings the string of information is encrypted using the AES 256 module of the PyCrypto library. A password is
specified by the user upon creation of the settings file. A hashed (thus unreadable) version of the password is stored
locally in the .ps.sync file in the home folder of the user. Upon launch of CanvasSync, the user must specify
a password that matches the one stored in the hashed version. If the password is correct the the settings file is
decrypted and parsed for settings.
"""

# Future imports
from __future__ import print_function

# Inbuilt modules
import getpass
import os
import os.path
import sys

# Third party modules
import bcrypt
from Crypto.Cipher import AES
from Crypto.Hash import SHA256
from Crypto.Util.Padding import pad, unpad


def get_key_hash(password):
    """ Get a 256 byte SHA hash from any length password or bytes """
    if isinstance(password, bytes):
        data = password
    else:
        data = password.encode(u"utf-8")
    hasher = SHA256.new(data)
    return hasher.digest()


def _pw_file_path():
    # Allow override so multiple Canvas instances (e.g. PSU + Emeritus) can
    # coexist without overwriting each other's bcrypt-hash-derived AES key.
    env_pw_path = os.environ.get("CANVASSYNC_PW_PATH")
    if env_pw_path:
        return os.path.abspath(os.path.expanduser(env_pw_path))
    return os.path.expanduser(u"~") + u"/.CanvasSync.pw"


def encrypt(message):
    """
    Encrypts a string using AES-256 (CBC) encryption
    A random initialization vector (IV) is padded as the initial 16 bytes of the string
    The encrypted message will be padded to length%16 = 0 bytes (AES needs 16 bytes block sizes)
    """

    # allow non-interactive setup via env var
    env_pw = os.environ.get("CANVASSYNC_PASSWORD")
    if env_pw is not None:
        password_bytes = env_pw.encode()
    else:
        print(u"\nPlease enter a password to encrypt the settings file:")
        password_bytes = getpass.getpass().encode()
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    with open(_pw_file_path(), "wb") as pass_file:
        # store bcrypt hash bytes as-is
        pass_file.write(hashed_password)

    # Generate random 16 bytes IV
    IV = os.urandom(16)

    # AES object
    encrypter = AES.new(get_key_hash(hashed_password), AES.MODE_CBC, IV)

    # Add the unencrypted IV to the beginning of the encrypted_message
    encrypted_message = IV + encrypter.encrypt(pad(message.encode("utf-8"), 16))

    return encrypted_message


def decrypt(message, password):
    """
    Decrypts an AES encrypted string
    """

    # Load the locally stored bcrypt hashed password (answer)
    path = _pw_file_path()
    if not os.path.exists(path):
        return False

    with open(path, "rb") as pw_file:
        hashed_password = pw_file.read()

    # Get password from user and compare to answer
    valid_password = False

    # If the password isn't null then it was specified as a command-line argument
    # support passing password via env var too
    if not password:
        password = os.environ.get("CANVASSYNC_PASSWORD") or password

    if password:
        if not bcrypt.checkpw(password.encode(), hashed_password):
            print(u"\n[ERROR] Invalid password. Please try again or invoke CanvasSync with the -s flag to reset settings.")
            sys.exit()
    else:
        # Otherwise, get the password from the user
        while not valid_password:
            print(u"\nPlease enter password to decrypt the settings file:")
            password = getpass.getpass()
            if bcrypt.checkpw(password.encode(), hashed_password):
                valid_password = True
            else:
                print(u"\n[ERROR] Invalid password. Please try again or invoke CanvasSync with the -s flag to reset settings.")

    # Read the remote IV
    remoteIV = message[:16]

    # Decrypt message using the correct password
    decrypter = AES.new(get_key_hash(hashed_password), AES.MODE_CBC, remoteIV)
    decrypted_message = decrypter.decrypt(message[16:])
    decrypted_message = unpad(decrypted_message, 16)

    return decrypted_message
