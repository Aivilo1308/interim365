# -*- coding: utf-8 -*-
"""
Context Processor pour les jours fériés

Ajouter dans settings.py -> TEMPLATES -> OPTIONS -> context_processors:
    'mainapp.context_processors.jours_feries_context',

Fichier à placer dans: mainapp/context_processors.py
"""

from datetime import date
from django.core.cache import cache

# Délai maximum en jours pour afficher l'étiquette du prochain férié
DELAI_AFFICHAGE_FERIE = 15


def jours_feries_context(request):
    """
    Injecte les informations du prochain jour férié dans tous les templates
    
    L'étiquette ne s'affiche que si le prochain férié arrive dans les 15 jours ou moins.
    
    Variables disponibles dans les templates:
        - prochain_ferie: Instance JourFerie du prochain férié (ou None si > 15 jours)
        - prochain_ferie_jours: Nombre de jours avant le prochain férié
        - prochain_ferie_est_musulman: Bool si c'est un férié musulman
        - prochain_ferie_est_modifiable: Bool si la date est modifiable
        - prochain_ferie_afficher: Bool indiquant si on doit afficher l'étiquette
    """
    # Utiliser le cache pour éviter les requêtes répétées
    cache_key = 'prochain_ferie_context'
    context = cache.get(cache_key)
    
    if context is None:
        try:
            from mainapp.models import JourFerie, TypeJourFerie
            
            prochain = JourFerie.objects.prochain_ferie()
            
            if prochain:
                jours_avant = (prochain.date_ferie - date.today()).days
                est_musulman = prochain.type_ferie == TypeJourFerie.FERIE_MUSULMAN
                est_modifiable = prochain.modele.est_modifiable if prochain.modele else False
                
                # Afficher l'étiquette seulement si <= 15 jours
                afficher = jours_avant <= DELAI_AFFICHAGE_FERIE
                
                context = {
                    'prochain_ferie': prochain if afficher else None,
                    'prochain_ferie_jours': jours_avant,
                    'prochain_ferie_est_musulman': est_musulman,
                    'prochain_ferie_est_modifiable': est_modifiable,
                    'prochain_ferie_afficher': afficher,
                    'prochain_ferie_delai_max': DELAI_AFFICHAGE_FERIE,
                }
            else:
                context = {
                    'prochain_ferie': None,
                    'prochain_ferie_jours': None,
                    'prochain_ferie_est_musulman': False,
                    'prochain_ferie_est_modifiable': False,
                    'prochain_ferie_afficher': False,
                    'prochain_ferie_delai_max': DELAI_AFFICHAGE_FERIE,
                }
            
            # Cache pour 1 heure (3600 secondes)
            cache.set(cache_key, context, 3600)
            
        except Exception as e:
            # En cas d'erreur, retourner un contexte vide
            context = {
                'prochain_ferie': None,
                'prochain_ferie_jours': None,
                'prochain_ferie_est_musulman': False,
                'prochain_ferie_est_modifiable': False,
                'prochain_ferie_afficher': False,
                'prochain_ferie_delai_max': DELAI_AFFICHAGE_FERIE,
            }
    
    return context