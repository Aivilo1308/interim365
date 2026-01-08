#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâches Celery pour la gestion des jours fériés - Côte d'Ivoire

Emplacement: mainapp/tasks.py (ajouter à votre fichier tasks.py existant)

Configuration Celery Beat dans settings.py:

    from celery.schedules import crontab
    
    CELERY_BEAT_SCHEDULE = {
        'verifier-jours-feries-quotidien': {
            'task': 'mainapp.tasks.verifier_et_creer_jours_feries',
            'schedule': crontab(hour=6, minute=0),
        },
    }
"""

from celery import shared_task
from datetime import date
from typing import Dict, Optional
from django.db import transaction
from django.utils import timezone

import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_kelio_global_task(self):
    """
    Tâche Celery pour synchronisation globale Kelio.
    Exécute la synchronisation des employés, absences, formations et compétences.
    
    Retries: 3 tentatives avec délai de 5 minutes entre chaque
    """
    logger.info("=" * 80)
    logger.info("[CELERY-KELIO] DEBUT SYNCHRONISATION AUTOMATIQUE KELIO")
    logger.info(f"[CELERY-KELIO] Timestamp: {timezone.now().isoformat()}")
    logger.info("=" * 80)
    
    try:
        from mainapp.services.kelio_sync_v43 import KelioGlobalSyncManagerV43
        
        # Créer le manager de synchronisation
        manager = KelioGlobalSyncManagerV43(
            sync_mode='complete',
            force_sync=True,
            notify_users=False,
            include_archived=False
        )
        
        # Exécuter la synchronisation
        result = manager.execute_global_sync()
        
        # Log du résultat
        if result.get('success'):
            logger.info("[CELERY-KELIO] ✅ Synchronisation terminée avec succès")
            logger.info(f"[CELERY-KELIO] Stats: {result.get('stats', {})}")
        else:
            logger.warning(f"[CELERY-KELIO] ⚠️ Synchronisation partielle: {result.get('message')}")
        
        logger.info("=" * 80)
        logger.info("[CELERY-KELIO] FIN SYNCHRONISATION AUTOMATIQUE")
        logger.info("=" * 80)
        
        return {
            'success': result.get('success', False),
            'message': result.get('message', ''),
            'timestamp': timezone.now().isoformat(),
            'stats': result.get('stats', {})
        }
        
    except Exception as e:
        logger.error(f"[CELERY-KELIO] ❌ ERREUR: {str(e)}")
        
        # Retry automatique
        try:
            raise self.retry(exc=e)
        except self.MaxRetriesExceededError:
            logger.error("[CELERY-KELIO] ❌ Nombre max de tentatives atteint")
            return {
                'success': False,
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            }
        
@shared_task(
    bind=True,
    name='mainapp.tasks.verifier_et_creer_jours_feries',
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={'max_retries': 3},
)
def verifier_et_creer_jours_feries(
    self,
    annee: Optional[int] = None,
    annees_suivantes: int = 1,
    code_pays: str = 'CI'
) -> Dict:
    """
    Vérifie si les jours fériés standards de l'année pour la Côte d'Ivoire
    sont créés. S'ils ne le sont pas, les crée automatiquement.
    
    Args:
        annee: Année de départ (année courante par défaut)
        annees_suivantes: Nombre d'années à vérifier en avance
        code_pays: Code pays ISO (CI par défaut)
        
    Returns:
        Dict avec les résultats
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
            # Étape 1: Vérifier/Créer les modèles
            nb_modeles = ModeleJourFerie.objects.actifs(code_pays).count()
            
            if nb_modeles == 0:
                logger.info("[JoursFeries] Initialisation des modèles...")
                init = ModeleJourFerie.objects.charger_donnees_initiales(code_pays)
                resultats['modeles_initialises'] = True
                resultats['modeles_crees'] = len(init.get('crees', []))
                nb_modeles = resultats['modeles_crees']
                logger.info(f"[JoursFeries] {nb_modeles} modèles créés")
            
            # Étape 2: Vérifier/Créer les jours fériés par année
            for a in range(annee, annee + annees_suivantes + 1):
                nb_existants = JourFerie.objects.filter(
                    annee=a, code_pays=code_pays
                ).count()
                
                if nb_existants >= nb_modeles:
                    logger.debug(f"[JoursFeries] {a}: complet ({nb_existants})")
                    resultats['annees'][a] = {'statut': 'complet', 'crees': 0}
                    continue
                
                # Générer les manquants
                logger.info(f"[JoursFeries] {a}: génération...")
                gen = JourFerie.objects.generer_annee(a, code_pays, 'celery_task')
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


def verifier_jours_feries_sync(
    annee: Optional[int] = None,
    annees_suivantes: int = 1,
    code_pays: str = 'CI',
    verbose: bool = False
) -> Dict:
    """
    Version synchrone (sans Celery) pour tests ou appels manuels
    
    Usage:
        from mainapp.tasks import verifier_jours_feries_sync
        verifier_jours_feries_sync(verbose=True)
    """
    from mainapp.models import ModeleJourFerie, JourFerie
    
    if annee is None:
        annee = date.today().year
    
    resultats = {'succes': True, 'annees': {}, 'total_crees': 0}
    
    # Modèles
    if not ModeleJourFerie.objects.actifs(code_pays).exists():
        if verbose:
            print("→ Initialisation des modèles...")
        init = ModeleJourFerie.objects.charger_donnees_initiales(code_pays)
        if verbose:
            print(f"  ✓ {len(init.get('crees', []))} modèles créés")
    
    nb_modeles = ModeleJourFerie.objects.actifs(code_pays).count()
    
    # Années
    for a in range(annee, annee + annees_suivantes + 1):
        nb_existants = JourFerie.objects.filter(annee=a, code_pays=code_pays).count()
        
        if nb_existants >= nb_modeles:
            if verbose:
                print(f"[{a}] ✓ Complet ({nb_existants} jours fériés)")
            resultats['annees'][a] = {'crees': 0}
        else:
            if verbose:
                print(f"[{a}] → Génération...")
            gen = JourFerie.objects.generer_annee(a, code_pays, 'sync')
            nb_crees = len(gen.get('crees', []))
            resultats['annees'][a] = {'crees': nb_crees}
            resultats['total_crees'] += nb_crees
            if verbose:
                print(f"      ✓ {nb_crees} créé(s)")
    
    return resultats