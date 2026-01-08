#!/usr/bin/env python3
"""
Script pour créer rapidement les fichiers de log Kelio
Exécutez avec : python create_logs.py
"""

from pathlib import Path
import os
from datetime import datetime

def create_logs():
    """Crée les fichiers et répertoires de log nécessaires"""
    
    print("🔧 Création des logs Kelio...")
    
    # Détecter le répertoire du projet
    current_dir = Path.cwd()
    
    # Chercher manage.py pour confirmer qu'on est dans un projet Django
    if (current_dir / 'manage.py').exists():
        base_dir = current_dir
        print(f"✅ Projet Django détecté: {base_dir}")
    else:
        base_dir = current_dir
        print(f"⚠️  manage.py non trouvé, utilisation de: {base_dir}")
    
    # Créer le répertoire logs
    logs_dir = base_dir / 'logs'
    
    try:
        logs_dir.mkdir(exist_ok=True)
        print(f"✅ Répertoire logs créé: {logs_dir}")
    except Exception as e:
        print(f"❌ Erreur création répertoire logs: {e}")
        return False
    
    # Créer les fichiers de log
    log_files = [
        'kelio_api.log',
        'interim.log',
        'kelio_sync.log'
    ]
    
    created_count = 0
    
    for log_file in log_files:
        log_path = logs_dir / log_file
        
        try:
            # Créer le fichier
            log_path.touch()
            
            # Ajouter un en-tête
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"# Log Kelio - {log_file}\n")
                f.write(f"# Créé le: {datetime.now()}\n")
                f.write(f"# Système d'intérim - Log {log_file.replace('.log', '')}\n")
                f.write("\n")
            
            print(f"✅ Fichier créé: {log_file}")
            created_count += 1
            
        except Exception as e:
            print(f"❌ Erreur création {log_file}: {e}")
    
    # Test des permissions
    print("\n🔍 Test des permissions d'écriture...")
    
    for log_file in log_files:
        log_path = logs_dir / log_file
        
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(f"# Test écriture - {datetime.now()}\n")
            print(f"✅ {log_file} - Écriture OK")
        except Exception as e:
            print(f"❌ {log_file} - Erreur écriture: {e}")
    
    # Créer la structure pour la commande Django (optionnel)
    print("\n📁 Création structure commande Django...")
    
    try:
        # Créer les répertoires pour la commande
        management_dir = base_dir / 'mainapp' / 'management'
        commands_dir = management_dir / 'commands'
        
        management_dir.mkdir(parents=True, exist_ok=True)
        commands_dir.mkdir(exist_ok=True)
        
        # Créer les fichiers __init__.py
        init_files = [
            base_dir / 'mainapp' / '__init__.py',
            management_dir / '__init__.py',
            commands_dir / '__init__.py'
        ]
        
        for init_file in init_files:
            if not init_file.exists():
                init_file.touch()
                print(f"✅ Créé: {init_file.relative_to(base_dir)}")
        
    except Exception as e:
        print(f"⚠️  Structure commande non créée: {e}")
    
    # Résumé
    print("\n" + "="*50)
    print("📊 RÉSUMÉ")
    print("="*50)
    print(f"📁 Répertoire logs: {logs_dir}")
    print(f"📝 Fichiers créés: {created_count}/{len(log_files)}")
    
    if created_count == len(log_files):
        print("🎉 Tous les logs ont été créés avec succès!")
        
        # Instructions suivantes
        print("\n📋 PROCHAINES ÉTAPES:")
        print("1. Ajoutez la configuration LOGGING dans settings.py")
        print("2. Modifiez votre service Kelio pour utiliser le SafeLogger")
        print("3. Testez avec: python manage.py runserver")
        
        return True
    else:
        print("⚠️  Certains fichiers n'ont pas pu être créés")
        return False

def create_repair_command():
    """Crée le fichier de commande repair_logs.py"""
    
    base_dir = Path.cwd()
    commands_dir = base_dir / 'mainapp' / 'management' / 'commands'
    repair_file = commands_dir / 'repair_logs.py'
    
    if repair_file.exists():
        print(f"ℹ️  Le fichier repair_logs.py existe déjà")
        return True
    
    try:
        # Contenu de la commande
        command_content = '''from django.core.management.base import BaseCommand
from django.utils import timezone
from pathlib import Path
import os

class Command(BaseCommand):
    help = 'Répare et initialise le système de logging'
    
    def handle(self, *args, **options):
        self.stdout.write("🔧 Réparation du système de logging...")
        
        # Créer logs
        base_dir = Path.cwd()
        logs_dir = base_dir / 'logs'
        logs_dir.mkdir(exist_ok=True)
        
        log_files = ['kelio_api.log', 'interim.log', 'kelio_sync.log']
        
        for log_file in log_files:
            log_path = logs_dir / log_file
            if not log_path.exists():
                log_path.touch()
                self.stdout.write(f"✅ Créé: {log_file}")
            else:
                self.stdout.write(f"ℹ️  Existe: {log_file}")
        
        self.stdout.write(
            self.style.SUCCESS('✅ Réparation terminée')
        )
'''
        
        with open(repair_file, 'w', encoding='utf-8') as f:
            f.write(command_content)
        
        print(f"✅ Commande créée: {repair_file}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur création commande: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Script de création des logs Kelio")
    print("="*40)
    
    # Créer les logs
    success = create_logs()
    
    if success:
        # Créer la commande Django
        create_repair_command()
        
        print("\n✅ Script terminé avec succès!")
        print("Vous pouvez maintenant utiliser:")
        print("  python manage.py repair_logs")
    else:
        print("\n❌ Script terminé avec des erreurs")