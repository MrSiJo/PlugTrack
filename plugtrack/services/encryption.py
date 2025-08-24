import os
from cryptography.fernet import Fernet
from base64 import b64encode, b64decode

class EncryptionService:
    def __init__(self, key=None):
        if key is None:
            # Generate a new key if none provided
            key = Fernet.generate_key()
        self.cipher_suite = Fernet(key)
    
    def encrypt(self, data: str) -> str:
        """Encrypt a string and return base64 encoded result"""
        if not data:
            return data
        encrypted_data = self.cipher_suite.encrypt(data.encode())
        return b64encode(encrypted_data).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt a base64 encoded encrypted string"""
        if not encrypted_data:
            return encrypted_data
        try:
            decoded_data = b64decode(encrypted_data.encode())
            decrypted_data = self.cipher_suite.decrypt(decoded_data)
            return decrypted_data.decode()
        except Exception:
            # Return original data if decryption fails
            return encrypted_data
    
    @classmethod
    def generate_key(cls) -> str:
        """Generate a new encryption key"""
        return Fernet.generate_key().decode()
    
    @classmethod
    def from_env_key(cls, env_var_name: str = 'ENCRYPTION_KEY'):
        """Create service instance from environment variable"""
        key = os.environ.get(env_var_name)
        if not key:
            raise ValueError(f"Environment variable {env_var_name} not set")
        return cls(key.encode())
