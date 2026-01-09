# mainapp/management/commands/migrate_kelio_passwords.py
from django.core.management.base import BaseCommand
from django.conf import settings
from cryptography.fernet import Fernet
import base64
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Migre les mots de passe Kelio du format clair au format crypté'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simule la migration sans modifier la base'
        )
    
    def handle(self, *args, **options):
        from mainapp.models import ConfigurationApiKelio
        
        dry_run = options['dry_run']
        
        self.stdout.write(self.style.SUCCESS("🚀 Début de la migration des mots de passe Kelio..."))
        
        # Vérifier la clé de cryptage
        try:
            secret_key = settings.KELIO_CRYPTO_KEY
            if isinstance(secret_key, str):
                secret_key = secret_key.encode('utf-8')
            cipher = Fernet(secret_key)
        except AttributeError:
            self.stdout.write(self.style.ERROR("❌ Clé KELIO_CRYPTO_KEY non trouvée dans settings.py"))
            return
        
        # Récupérer toutes les configurations
        configs = ConfigurationApiKelio.objects.all()
        
        migrated = 0
        skipped = 0
        errors = 0
        
        for config in configs:
            try:
                # Vérifier si le champ crypté existe
                if not hasattr(config, '_password_encrypted'):
                    self.stdout.write(self.style.WARNING(
                        f"⚠️ {config.nom}: Champ _password_encrypted non trouvé"
                    ))
                    skipped += 1
                    continue
                
                # Si déjà crypté
                if config._password_encrypted:
                    self.stdout.write(self.style.WARNING(
                        f"⏭️ {config.nom}: Déjà crypté"
                    ))
                    skipped += 1
                    continue
                
                # Vérifier le mot de passe en clair
                if not config.password:
                    self.stdout.write(self.style.WARNING(
                        f"⚠️ {config.nom}: Pas de mot de passe à migrer"
                    ))
                    skipped += 1
                    continue
                
                # Crypter le mot de passe
                encrypted = cipher.encrypt(config.password.encode('utf-8'))
                encrypted_str = base64.urlsafe_b64encode(encrypted).decode('utf-8')
                
                if not dry_run:
                    config._password_encrypted = encrypted_str
                    config.save()
                
                self.stdout.write(self.style.SUCCESS(
                    f"✅ {config.nom}: {'(DRY RUN) ' if dry_run else ''}Crypté avec succès"
                ))
                migrated += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"❌ {config.nom}: Erreur - {str(e)}"
                ))
                errors += 1
        
        # Résumé
        self.stdout.write("\n" + "="*50)
        self.stdout.write(self.style.SUCCESS("📊 RÉSULTAT DE LA MIGRATION"))
        self.stdout.write("="*50)
        
        if dry_run:
            self.stdout.write(self.style.WARNING("⚠️ MODE SIMULATION (dry-run) - Aucune modification"))
        
        self.stdout.write(f"✅ Migrés: {migrated}")
        self.stdout.write(f"⏭️ Ignorés: {skipped}")
        self.stdout.write(f"❌ Erreurs: {errors}")
        
        if not dry_run and migrated > 0:
            self.stdout.write(self.style.SUCCESS(
                f"\n🎉 Migration terminée avec succès! {migrated} mot(s) de passe crypté(s)."
            ))