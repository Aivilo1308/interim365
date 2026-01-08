# CONTENU À COPIER DANS management/commands/repair_logs.py

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from pathlib import Path
import logging
import os

class Command(BaseCommand):
    help = 'Répare et initialise le système de logging pour Kelio'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Affichage détaillé des opérations',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force la recréation des fichiers existants',
        )
    
    def handle(self, *args, **options):
        verbosity = options.get('verbosity', 1)
        verbose = options.get('verbose', False)
        force = options.get('force', False)
        
        self.stdout.write(
            self.style.HTTP_INFO("🔧 Réparation du système de logging Kelio...")
        )
        
        # Obtenir le répertoire de base
        try:
            base_dir = getattr(settings, 'BASE_DIR', Path.cwd())
            logs_dir = Path(base_dir) / 'logs'
            
            if verbose:
                self.stdout.write(f"📁 Répertoire de base: {base_dir}")
                self.stdout.write(f"📁 Répertoire logs: {logs_dir}")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Erreur configuration BASE_DIR: {e}")
            )
            return
        
        # Créer le répertoire logs s'il n'existe pas
        try:
            logs_dir.mkdir(exist_ok=True)
            self.stdout.write(
                self.style.SUCCESS(f"✅ Répertoire logs créé/vérifié: {logs_dir}")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Impossible de créer le répertoire logs: {e}")
            )
            return
        
        # Vérifier/créer les fichiers de log
        log_files = [
            'kelio_api.log',
            'interim.log',
            'kelio_sync.log'
        ]
        
        self.stdout.write("\n📝 Vérification des fichiers de log...")
        
        files_status = {}
        for log_file in log_files:
            log_path = logs_dir / log_file
            
            try:
                if log_path.exists():
                    if force:
                        # Sauvegarder l'ancien fichier
                        backup_path = logs_dir / f"{log_file}.backup"
                        if backup_path.exists():
                            backup_path.unlink()
                        log_path.rename(backup_path)
                        
                        # Créer nouveau fichier
                        with open(log_path, 'w', encoding='utf-8') as f:
                            f.write(f"# Log {log_file} - Recréé le {timezone.now()}\n")
                            f.write("# Système d'intérim Kelio\n\n")
                        
                        files_status[log_file] = "recréé"
                        self.stdout.write(f"🔄 Fichier recréé: {log_file}")
                    else:
                        files_status[log_file] = "existant"
                        if verbose:
                            self.stdout.write(f"ℹ️  Fichier existe: {log_file}")
                else:
                    # Créer le fichier
                    with open(log_path, 'w', encoding='utf-8') as f:
                        f.write(f"# Log {log_file} - Créé le {timezone.now()}\n")
                        f.write("# Système d'intérim Kelio\n\n")
                    
                    files_status[log_file] = "créé"
                    self.stdout.write(
                        self.style.SUCCESS(f"✅ Fichier créé: {log_file}")
                    )
                
            except Exception as e:
                files_status[log_file] = f"erreur: {e}"
                self.stdout.write(
                    self.style.ERROR(f"❌ Erreur avec {log_file}: {e}")
                )
        
        # Test des permissions d'écriture
        self.stdout.write("\n🔍 Test des permissions d'écriture...")
        
        write_tests = {}
        for log_file in log_files:
            log_path = logs_dir / log_file
            
            if log_path.exists():
                try:
                    # Test d'écriture
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(f"# Test écriture repair_logs - {timezone.now()}\n")
                    
                    write_tests[log_file] = "OK"
                    self.stdout.write(f"✅ {log_file} - Écriture OK")
                    
                except Exception as e:
                    write_tests[log_file] = f"Erreur: {e}"
                    self.stdout.write(
                        self.style.ERROR(f"❌ {log_file} - Erreur écriture: {e}")
                    )
            else:
                write_tests[log_file] = "Fichier manquant"
                self.stdout.write(
                    self.style.WARNING(f"⚠️  {log_file} - Fichier manquant")
                )
        
        # Test de la configuration LOGGING dans settings
        self.stdout.write("\n🧪 Test configuration LOGGING...")
        
        try:
            logging_config = getattr(settings, 'LOGGING', None)
            if logging_config:
                self.stdout.write("✅ Configuration LOGGING trouvée dans settings")
                
                # Tester les handlers
                handlers = logging_config.get('handlers', {})
                kelio_handlers = [h for h in handlers.keys() if 'kelio' in h or 'interim' in h]
                
                if kelio_handlers:
                    self.stdout.write(f"✅ Handlers Kelio trouvés: {', '.join(kelio_handlers)}")
                else:
                    self.stdout.write(
                        self.style.WARNING("⚠️  Aucun handler Kelio trouvé dans la configuration")
                    )
                
                # Test des loggers
                test_loggers = ['kelio.sync', 'interim', 'kelio']
                for logger_name in test_loggers:
                    try:
                        test_logger = logging.getLogger(logger_name)
                        test_logger.info(f"Test logger {logger_name} depuis repair_logs - {timezone.now()}")
                        self.stdout.write(f"✅ Logger {logger_name} - Test réussi")
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f"⚠️  Logger {logger_name} - Erreur: {e}")
                        )
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  Configuration LOGGING non trouvée dans settings")
                )
                self.stdout.write("   Ajoutez la configuration LOGGING dans votre settings.py")
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Erreur test logging: {e}")
            )
        
        # Test SafeLogger
        self.stdout.write("\n🛡️  Test SafeLogger...")
        
        try:
            safe_logger_func = getattr(settings, 'get_safe_kelio_logger', None)
            if safe_logger_func:
                safe_logger = safe_logger_func()
                safe_logger.info(f"Test SafeLogger depuis repair_logs - {timezone.now()}")
                self.stdout.write("✅ SafeLogger - Fonctionnel")
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  get_safe_kelio_logger non trouvé dans settings")
                )
                self.stdout.write("   Ajoutez SafeLogger dans votre settings.py")
                
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"⚠️  SafeLogger test échoué: {e}")
            )
        
        # Vérification de la structure des apps
        self.stdout.write("\n📦 Vérification structure Django...")
        
        try:
            installed_apps = getattr(settings, 'INSTALLED_APPS', [])
            
            # Vérifier si mainapp est dans INSTALLED_APPS
            mainapp_installed = any('mainapp' in app for app in installed_apps)
            
            if mainapp_installed:
                self.stdout.write("✅ mainapp trouvée dans INSTALLED_APPS")
            else:
                self.stdout.write(
                    self.style.WARNING("⚠️  mainapp non trouvée dans INSTALLED_APPS")
                )
                self.stdout.write("   Ajoutez 'mainapp' dans INSTALLED_APPS de settings.py")
            
        except Exception as e:
            self.stdout.write(f"⚠️  Erreur vérification apps: {e}")
        
        # Résumé final avec statistiques
        self.stdout.write("\n" + "="*60)
        self.stdout.write("📊 RÉSUMÉ DE LA RÉPARATION")
        self.stdout.write("="*60)
        
        # Statistiques des fichiers
        created_count = len([s for s in files_status.values() if s in ['créé', 'recréé']])
        existing_count = len([s for s in files_status.values() if s == 'existant'])
        error_count = len([s for s in files_status.values() if s.startswith('erreur')])
        
        self.stdout.write(f"📁 Répertoire logs: {logs_dir}")
        self.stdout.write(f"📝 Fichiers créés/recréés: {created_count}")
        self.stdout.write(f"📄 Fichiers existants: {existing_count}")
        if error_count > 0:
            self.stdout.write(
                self.style.ERROR(f"❌ Fichiers en erreur: {error_count}")
            )
        
        # Statistiques des tests d'écriture
        write_ok_count = len([t for t in write_tests.values() if t == 'OK'])
        write_error_count = len(write_tests) - write_ok_count
        
        self.stdout.write(f"✍️  Tests d'écriture réussis: {write_ok_count}/{len(write_tests)}")
        
        # Statut global
        total_files = len(log_files)
        successful_files = created_count + existing_count
        
        if successful_files == total_files and write_ok_count == total_files:
            self.stdout.write(
                self.style.SUCCESS("\n🎉 RÉPARATION COMPLÈTEMENT RÉUSSIE!")
            )
            self.stdout.write("   Tous les fichiers de log sont opérationnels.")
        elif successful_files == total_files:
            self.stdout.write(
                self.style.WARNING("\n⚠️  RÉPARATION PARTIELLEMENT RÉUSSIE")
            )
            self.stdout.write("   Fichiers créés mais problèmes d'écriture détectés.")
        else:
            self.stdout.write(
                self.style.ERROR("\n❌ RÉPARATION INCOMPLÈTE")
            )
            self.stdout.write("   Certains fichiers n'ont pas pu être créés.")
        
        # Instructions suivantes
        self.stdout.write("\n" + "="*60)
        self.stdout.write("📋 PROCHAINES ÉTAPES RECOMMANDÉES")
        self.stdout.write("="*60)
        
        steps = [
            "1. ✅ Vérifiez que 'mainapp' est dans INSTALLED_APPS (settings.py)",
            "2. ✅ Ajoutez la configuration LOGGING dans settings.py",
            "3. ✅ Ajoutez SafeLogger dans settings.py",
            "4. 🧪 Testez votre service Kelio:",
            "     from django.conf import settings",
            "     logger = settings.get_safe_kelio_logger()",
            "     logger.info('Test logging réparé')",
            "5. 🚀 Redémarrez votre serveur Django",
        ]
        
        for step in steps:
            self.stdout.write(f"   {step}")
        
        self.stdout.write(f"\n💡 Tip: Utilisez --verbose pour plus de détails")
        self.stdout.write(f"💡 Tip: Utilisez --force pour recréer les fichiers")
        
        # Retourner le code de sortie approprié
        if successful_files == total_files and write_ok_count == total_files:
            return  # Succès complet
        else:
            raise Exception("Réparation incomplète - voir les détails ci-dessus")