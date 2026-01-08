#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâches Cron pour mainapp - Remplace les tâches Celery

Emplacement: mainapp/cron.py
"""

import logging
from datetime import date
from typing import Dict, Optional
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def sync_kelio_global():
    """
    Tâche cron pour synchronisation globale Kelio.
    Remplace sync_kelio_global_task de Celery.
    """
    logger.info("=" * 80)
    logger.info("[CRON-KELIO] DEBUT SYNCHRONISATION AUTOMATIQUE KELIO")
    logger.info(f"[CRON-KELIO] Timestamp: {timezone.now().isoformat()}")
    logger.info("=" * 80)
    
    try:
        from mainapp.services.kelio_sync_v43 import KelioGlobalSyncManagerV43
        
        manager = KelioGlobalSyncManagerV43(
            sync_mode='complete',
            force_sync=True,
            notify_users=False,
            include_archived=False
        )
        
        result = manager.execute_global_sync()
        
        if result.get('success'):
            logger.info("[CRON-KELIO] ✅ Synchronisation terminée avec succès")
            logger.info(f"[CRON-KELIO] Stats: {result.get('stats', {})}")
        else:
            logger.warning(f"[CRON-KELIO] ⚠️ Synchronisation partielle: {result.get('message')}")
        
        logger.info("=" * 80)
        logger.info("[CRON-KELIO] FIN SYNCHRONISATION AUTOMATIQUE")
        logger.info("=" * 80)
        
        return result
        
    except Exception as e:
        logger.error(f"[CRON-KELIO] ❌ ERREUR: {str(e)}")
        raise


def verifier_jours_feries(annee: Optional[int] = None, annees_suivantes: int = 1, code_pays: str = 'CI'):
    """
    Vérifie et crée les jours fériés.
    Remplace verifier_et_creer_jours_feries de Celery.
    """
    from mainapp.models import ModeleJourFerie, JourFerie
    
    if annee is None:
        annee = date.today().year
    
    logger.info(f"[JoursFeries] Vérification {code_pays} - {annee} (+{annees_suivantes} ans)")
    
    resultats = {
        'succes': True,
        'modeles_initialises': False,
        'annees': {},
        'total_crees': 0,
    }
    
    try:
        with transaction.atomic():
            nb_modeles = ModeleJourFerie.objects.actifs(code_pays).count()
            
            if nb_modeles == 0:
                logger.info("[JoursFeries] Initialisation des modèles...")
                init = ModeleJourFerie.objects.charger_donnees_initiales(code_pays)
                resultats['modeles_initialises'] = True
                resultats['modeles_crees'] = len(init.get('crees', []))
                nb_modeles = resultats['modeles_crees']
                logger.info(f"[JoursFeries] {nb_modeles} modèles créés")
            
            for a in range(annee, annee + annees_suivantes + 1):
                nb_existants = JourFerie.objects.filter(
                    annee=a, code_pays=code_pays
                ).count()
                
                if nb_existants >= nb_modeles:
                    logger.debug(f"[JoursFeries] {a}: complet ({nb_existants})")
                    resultats['annees'][a] = {'statut': 'complet', 'crees': 0}
                    continue
                
                logger.info(f"[JoursFeries] {a}: génération...")
                gen = JourFerie.objects.generer_annee(a, code_pays, 'cron_task')
                nb_crees = len(gen.get('crees', []))
                
                resultats['annees'][a] = {'statut': 'genere', 'crees': nb_crees}
                resultats['total_crees'] += nb_crees
                
                if nb_crees > 0:
                    logger.info(f"[JoursFeries] {a}: {nb_crees} créé(s)")
        
        logger.info(f"[JoursFeries] Terminé: {resultats['total_crees']} créé(s)")
        return resultats
        
    except Exception as e:
        logger.error(f"[JoursFeries] Erreur: {e}")
        raise