import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class KelioPasswordCipher:
    """Classe pour crypter/décrypter les mots de passe Kelio"""
    
    def __init__(self):
        # Clé de cryptage depuis les settings Django
        self.secret_key = getattr(settings, 'KELIO_CRYPTO_KEY', None)
        
        if not self.secret_key:
            # Générer une clé par défaut (à changer en production!)
            self.secret_key = self._generate_default_key()
            logger.warning("⚠️  Clé de cryptage Kelio non définie, utilisation d'une clé par défaut")
    
    def _generate_default_key(self):
        """Génère une clé par défaut (NE PAS UTILISER EN PRODUCTION)"""
        # En production, définissez KELIO_CRYPTO_KEY dans settings.py
        return Fernet.generate_key()
    
    def encrypt(self, plaintext):
        """
        Crypte un texte en clair
        
        Args:
            plaintext (str): Texte à crypter
            
        Returns:
            str: Texte crypté encodé en base64
        """
        if not plaintext:
            return ""
        
        try:
            # Convertir en bytes
            if isinstance(plaintext, str):
                plaintext = plaintext.encode('utf-8')
            
            # Créer le cipher
            cipher = Fernet(self.secret_key)
            
            # Crypter
            encrypted = cipher.encrypt(plaintext)
            
            # Encoder en base64 pour stockage texte
            return base64.urlsafe_b64encode(encrypted).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Erreur de cryptage: {e}")
            raise
    
    def decrypt(self, encrypted_text):
        """
        Décrypte un texte crypté
        
        Args:
            encrypted_text (str): Texte crypté en base64
            
        Returns:
            str: Texte décrypté
        """
        if not encrypted_text:
            return ""
        
        try:
            # Décoder le base64
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_text)
            
            # Créer le cipher
            cipher = Fernet(self.secret_key)
            
            # Décrypter
            decrypted = cipher.decrypt(encrypted_bytes)
            
            # Retourner en string
            return decrypted.decode('utf-8')
            
        except Exception as e:
            logger.error(f"Erreur de décryptage: {e}")
            # Retourner vide plutôt que de planter
            return ""