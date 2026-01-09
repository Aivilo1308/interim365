# Fichier : scripts/migrate_kelio_passwords.py
import os
import django
import sys

# Configuration Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'monapp.settings')
django.setup()

from mainapp.models import ConfigurationApiKelio
from utils.crypto_utils import KelioPasswordCipher
import logging

logger = logging.getLogger(__name__)

def migrate_existing_passwords():
    """
    Migre les mots de passe existants (en clair) vers le nouveau format crypté.
    À exécuter UNE SEULE FOIS après le déploiement.
    """
    cipher = KelioPasswordCipher()
    configs = ConfigurationApiKelio.objects.all()
    
    migrated = 0
    errors = 0
    
    for config in configs:
        try:
            # Vérifier si le mot de passe est déjà crypté
            current_password = config.password_encrypted
            
            if not current_password:
                # Mot de passe non défini
                logger.info(f"{config.nom}: Pas de mot de passe à migrer")
                continue
            
            # Essayer de décrypter (si ça échoue, c'est qu'il est en clair)
            try:
                decrypted = cipher.decrypt(current_password)
                if decrypted:  # Si décryptage réussi, c'est déjà crypté
                    logger.info(f"{config.nom}: Déjà crypté")
                    continue
            except:
                pass  # Pas crypté, on continue
            
            # Cryptage du mot de passe en clair
            encrypted = cipher.encrypt(current_password)
            config.password_encrypted = encrypted
            config.save(update_fields=['password_encrypted'])
            
            migrated += 1
            logger.info(f"{config.nom}: ✓ Migré avec succès")
            
        except Exception as e:
            errors += 1
            logger.error(f"{config.nom}: ❌ Erreur migration: {e}")
    
    logger.info(f"\nRésultat migration: {migrated} migrés, {errors} erreurs")
    return migrated, errors

if __name__ == "__main__":
    print("Migration des mots de passe Kelio...")
    migrate_existing_passwords()