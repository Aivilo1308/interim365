#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commande Django pour vérifier et créer les jours fériés CI

Emplacement: mainapp/management/commands/verifier_jours_feries.py

Structure requise:
    mainapp/
    └── management/
        ├── __init__.py
        └── commands/
            ├── __init__.py
            └── verifier_jours_feries.py  ← Ce fichier

Usage:
    python manage.py verifier_jours_feries
    python manage.py verifier_jours_feries --annee 2026
    python manage.py verifier_jours_feries --annees-suivantes 3
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from datetime import date


class Command(BaseCommand):
    help = "Vérifie et crée les jours fériés standards pour la Côte d'Ivoire"
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--annee', type=int, default=None,
            help="Année de départ (année courante par défaut)"
        )
        parser.add_argument(
            '--annees-suivantes', type=int, default=1,
            help="Nombre d'années à vérifier en avance (défaut: 1)"
        )
        parser.add_argument(
            '--code-pays', type=str, default='CI',
            help="Code pays ISO (défaut: CI)"
        )
        parser.add_argument(
            '--silencieux', action='store_true',
            help="Mode silencieux"
        )
    
    def handle(self, *args, **options):
        from mainapp.models import ModeleJourFerie, JourFerie
        
        annee = options['annee'] or date.today().year
        annees_suivantes = options['annees_suivantes']
        code_pays = options['code_pays']
        silencieux = options['silencieux']
        
        if not silencieux:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("  JOURS FÉRIÉS - CÔTE D'IVOIRE")
            self.stdout.write("=" * 60 + "\n")
        
        total_crees = 0
        
        with transaction.atomic():
            # Modèles
            nb_modeles = ModeleJourFerie.objects.actifs(code_pays).count()
            
            if nb_modeles == 0:
                if not silencieux:
                    self.stdout.write("  → Initialisation des modèles...")
                result = ModeleJourFerie.objects.charger_donnees_initiales(code_pays)
                nb_modeles = len(result.get('crees', []))
                if not silencieux:
                    self.stdout.write(self.style.SUCCESS(f"    ✓ {nb_modeles} modèles créés"))
            else:
                if not silencieux:
                    self.stdout.write(f"  ✓ {nb_modeles} modèles disponibles\n")
            
            # Années
            for a in range(annee, annee + annees_suivantes + 1):
                nb_existants = JourFerie.objects.filter(annee=a, code_pays=code_pays).count()
                
                if nb_existants >= nb_modeles:
                    if not silencieux:
                        self.stdout.write(f"  [{a}] ✓ Complet ({nb_existants} jours fériés)")
                    continue
                
                if not silencieux:
                    self.stdout.write(f"\n  [{a}] → Génération...")
                
                gen = JourFerie.objects.generer_annee(a, code_pays, 'management_command')
                nb_crees = len(gen.get('crees', []))
                total_crees += nb_crees
                
                if not silencieux and nb_crees > 0:
                    self.stdout.write(self.style.SUCCESS(f"    ✓ {nb_crees} créé(s)"))
                    for f in gen.get('crees', []):
                        self.stdout.write(f"      - {f.date_ferie.strftime('%d/%m/%Y')} : {f.nom}")
        
        if not silencieux:
            self.stdout.write("\n" + "-" * 60)
            if total_crees > 0:
                self.stdout.write(self.style.SUCCESS(f"  Total: {total_crees} jour(s) férié(s) créé(s)"))
            else:
                self.stdout.write(self.style.SUCCESS("  Tous les jours fériés sont déjà créés"))
            self.stdout.write("=" * 60 + "\n")
