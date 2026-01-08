# urls.py - Consolidé avec uniquement les vues existantes
"""
Fichier URLs consolidé ne contenant que les patterns correspondant 
aux vues réellement implémentées dans les fichiers views.py fournis.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Import des vues existantes
from mainapp import views, views_ajax, views_kelio, views_workflow_notif, views_employee_search, views_suite, views_jours_feries, views_absences_extraction

urlpatterns = [
    path('admin/', admin.site.urls),

    # ================================================================
    # AUTHENTIFICATION (views_auth.py)
    # ================================================================
    path('connexion/', views.connexion_view, name='connexion'),
    path('deconnexion/', views.deconnexion_view, name='deconnexion'),
    path('password-change/', views.password_change, name='password_change'),

    path('admin-config/', views.admin_configuration_view, name='admin_config'),
    path('admin-utilisateurs/', views.admin_utilisateurs_view, name='admin_utilisateurs'),    
    path('admin-logs/', views.admin_logs_view, name='admin_logs'),        

    path('admin-maintenance/', views.admin_maintenance_view, name='admin_maintenance'),    
    path('mentions-legales/', views.mentions_legales, name='mentions_legales'),    

    
    # ================================================================
    # TABLEAUX DE BORD HIÉRARCHIQUES (views_auth.py)
    # ================================================================
    path('', views.index, name='index'),
    path('n0/', views.index_chef_equipe, name='index_chef_equipe'),
    path('n1/', views.index_n1_responsable, name='index_n1_responsable'),
    path('n2/', views.index_n2_directeur, name='index_n2_directeur'),
    path('n3/', views.index_n3_global, name='index_n3_global'),
    
    # ================================================================
    # DEMANDES D'INTÉRIM (views.py)
    # ================================================================

    path('interim/mes-propositions/', views_suite.historique_mes_propositions, name='historique_mes_propositions'),

    path('interim/demande/', views.interim_demande, name='interim_demande'),
    path('interim/demande/<int:demande_id>/', views.demande_interim_detail_view, name='demande_detail'),
    
    path('interim/demande/<int:demande_id>/modifier/', views.demande_interim_update_view, name='demande_update'),
    path('interim/demande/<int:demande_id>/supprimer/', views.demande_interim_delete_view, name='demande_delete'),
    path('interim/demande/pour/<str:matricule>/', views.demande_interim_create_view, name='demande_pour_employe'),
    #path('interim/mes-demandes/', views.employe_mes_demandes, name='mes_demandes'),
    
    # Ajouter une nouvelle proposition à une demande d'intérim
    path('interim/ajax/demande/<int:demande_id>/ajouter-proposition/', views_suite.demande_interim_ajouter_proposition, 
     name='ajax_ajouter_proposition'),

    # Actions de validation
    #path('interim/demande/<int:demande_id>/valider/', views.valider_demande_avec_candidats, name='valider_demande_avec_candidats'),
    
    # Proposition candidat supplémentaire
    path('interim/demande/<int:demande_id>/proposer-candidat/', views.proposer_candidat_supplementaire, name='proposer_candidat_supplementaire'),

    path('interim/ajax/valider-coherence-departement/', views.ajax_valider_coherence_departement, name='ajax_valider_coherence_departement'),
    path('interim/ajax/departement/<int:departement_id>/info/', views.ajax_get_departement_info, name='ajax_departement_info'),

    # ================================================================
    # RECHERCHE ET SÉLECTION (views.py)
    # ================================================================
    path('interim/recherche/', views_suite.interim_recherche, name='interim_recherche'),

    path('interim/recherche/candidats/', views.recherche_candidats_avancee, name='recherche_candidats'),
    path('interim/recherche/ajax/', views.recherche_candidats_ajax, name='recherche_candidats_ajax'),
    path('interim/selection/', views.interim_selection, name='selection'),
    path('interim/selection/<int:demande_id>/', views.selection_candidats_view, name='selection_candidats'),
    
    # ================================================================
    # VALIDATIONS STANDARDS (views.py)
    # ================================================================
    path('interim/validation/<int:demande_id>/', views.demande_interim_validation, name='interim_validation'),
    path('interim/validation/liste/', views.validation_list_view, name='liste_interim_validation'),
    
    # À ajouter dans urls.py
    path('interim/api/validation/rapide/', views.validation_rapide, name='validation_rapide'),
    path('interim/api/validation/masse/', views.validation_masse, name='validation_masse'),

    # Nouvelle fonctionnalité de proposition rapide
    path('interim/validation/<int:demande_id>/proposer-rapide/', views.ajouter_proposition_validation, name='ajouter_proposition_validation'),

    path('interim/ajax/rechercher-candidats/', views.rechercher_candidats_ajax, name='rechercher_candidats_ajax'),
    path('interim/proposition/<int:proposition_id>/retirer/', views.retirer_proposition_ajax, name='retirer_proposition_ajax'),
    path('interim/mes-propositions/demande/<int:demande_id>/', views.mes_propositions_demande, name='mes_propositions_demande'),

    path('interim/escalader/<int:demande_id>/', views.escalader_demande, name='escalader_demande'),
    path('interim/verifier-escalade/<int:demande_id>/', views.verifier_escalade_possible, name='verifier_escalade_possible'),
    path('interim/historique-escalades/<int:demande_id>/', views.historique_escalades_demande, name='historique_escalades_demande'),

    path('interim/validation/<int:demande_id>/approuver/', views.approuver_demande_view, name='validation_approuver'),
    path('interim/validation/<int:demande_id>/refuser/', views.refuser_demande_view, name='validation_refuser'),

    # ================================================================
    # WORKFLOW ET NOTIFICATIONS (views_workflow_notif.py)
    # ================================================================

    path('interim/dashboard/workflow/', views_suite.workflow_global, name='workflow_global'),
   
    # Liste des notifications avec filtres avancés
    path('interim/notifications/', views_suite.mes_notifications, name='notifications'),
        
    # Actions en masse sur les notifications
    path('interim/actions/masse-notifications/', views_suite.actions_masse_notifications, name='actions_masse_notifications'),
    path('interim/actions/masse-notifications/diagnostic/', views_suite.diagnostic_selection_notifications, name='diagnostic_selection_notifications'),    
    
    # ================================================================
    # NOTIFICATIONS - URLs d'actions spécifiques
    # ================================================================
    
    # Marquer une notification comme traitée
    path('interim/notifications/<int:notification_id>/traiter/', views_suite.marquer_notification_traitee, name='marquer_notification_traitee'),
    
    # Marquer une notification comme lue
    path('interim/notifications/<int:notification_id>/marquer-lue/', views_suite.marquer_notification_lue, name='marquer_notification_lue'),
    
    # Marquer toutes les notifications comme lues
    path('interim/notifications/marquer-toutes-lues/', views_suite.marquer_toutes_notifications_lues, name='marquer_toutes_notifications_lues'),
    
    # Archiver une notification
    path('interim/notifications/<int:notification_id>/archiver/', views_suite.archiver_notification, name='archiver_notification'),
    
    # Supprimer une notification (admin seulement)
    path('interim/notifications/<int:notification_id>/supprimer/', views_suite.supprimer_notification, name='supprimer_notification'),
        
    # ================================================================
    # NOTIFICATIONS - URLs API pour AJAX
    # ================================================================
    
    # API pour compter les notifications non lues
    path('interim/api/notifications/count-non-lues/', views_suite.api_count_notifications_non_lues, name='api_count_notifications_non_lues'),
    
    # API pour récupérer les dernières notifications
    path('interim/api/notifications/recentes/', views_suite.api_notifications_recentes, name='api_notifications_recentes'),
    
    # ================================================================
    # HISTORIQUE ET SUIVI (views.py)
    # ================================================================
    path('interim/historique/', views_suite.historique_interim, name='historique_interim'),
    path('interim/stats/', views_suite.interim_stats, name='interim_stats'),

    path('interim/workflow/<int:demande_id>/', views.workflow_detail_view, name='workflow_detail'),
    path('interim/suivi/', views.suivi_demandes_view, name='suivi'),
    
    # ================================================================
    # GESTION DES EMPLOYÉS (views.py)
    # ================================================================
    path('interim/employes/', views.employes_list_view, name='employes_liste'),

    path('interim/employe/<str:matricule>/', views.employe_detail_view, name='employe_detail'),
    path('interim/employe-hierarchie/<str:matricule>/', views.employe_hierarchie, name='employe_hierarchie'),
    path('interim/employe/<int:demande_id>/<str:matricule>/', views.demande_employe_score, name='demande_employe_score'),
    path('interim/employe/<str:matricule>/disponibilite/', views.employe_disponibilite_view, name='employe_disponibilite'),
    path('interim/mes-missions/', views.employe_mes_missions, name='mes_missions'),
    #path('interim/employe/disponibilites/', views.employe_disponibilites, name='employe_disponibilites'),
    #path('interim/employe/profil/', views.profil_utilisateur_view, name='employe_profil'),

    path('manager/equipe/', views.manager_gestion_equipe, name='manager_gestion_equipe'),

    # ================================================================
    # PLANNING (views.py)
    # ================================================================
    path('interim/agenda/', views_suite.interim_agenda, name='agenda'),
    path('interim/agenda/evenement/<int:demande_id>/details/', views_suite.interim_agenda_event, name='agenda_event'),
    
    #path('interim/planning/<int:year>/<int:month>/', views.planning_mensuel_view, name='planning_mensuel'),
    #path('interim/planning/employe/<str:matricule>/', views.planning_employe_view, name='planning_employe'),
    
    # ================================================================
    # NOTES DE SERVICE (views.py)
    # ================================================================
    path('interim/notes/', views.interim_notes, name='interim_notes'),
    path('interim/notes/liste/', views.notes_service_list_view, name='notes_liste'),
    path('interim/notes/nouvelle/', views.notes_service_create_view, name='notes_nouvelle'),
    path('interim/notes/<int:pk>/', views.notes_service_detail_view, name='notes_detail'),
    path('interim/notes/<int:pk>/pdf/', views.generer_note_pdf_view, name='notes_pdf'),
       
     # API Formulaires
    path('interim/ajax/postes-by-departement/', views.ajax_get_postes_by_departement, name='ajax_postes_departement'),
    path('interim/ajax/employes-by-departement/', views.ajax_get_employes_by_departement, name='ajax_employes_departement'),
    path('ajax/candidats-departement/', views.ajax_get_candidats_departement, name='ajax_candidats_departement'),
    path('interim/ajax/verifier-disponibilite-candidat/', views.verifier_disponibilite_candidat_ajax, name='ajax_verifier_disponibilite'),

    # === API PROPOSITION AUTOMATIQUE ===
    path('interim/ajax/proposition-automatique/', views.ajax_proposition_automatique, name='ajax_proposition_automatique'),
    
    path('interim/ajax/calculer-score-candidat/', views.ajax_calculer_score_candidat, name='ajax_calculer_score_candidat'),
    
    # Recherche principale d'employé par matricule
    path('interim/ajax/rechercher-employe/', views_employee_search.rechercher_employe_ajax, name='ajax_rechercher_employe'),
   
    # Synchronisation Kelio d'un employé spécifique
    path('interim/ajax/sync-employe-kelio/', views_employee_search.sync_employe_kelio_ajax, name='sync_employe_kelio_ajax'),
    
    # Vérification de disponibilité pour les candidats
    path('interim/ajax/verifier-disponibilite-candidat/', views_employee_search.verifier_disponibilite_candidat_ajax, name='verifier_disponibilite_candidat_ajax'),
    
    # Recherche rapide pour autocomplétion
    path('interim/ajax/recherche-rapide-employes/', views_employee_search.recherche_rapide_employes_ajax, name='recherche_rapide_employes_ajax'),
    
    # Gestion du cache
    path('interim/ajax/invalider-cache-employe/', views_employee_search.invalider_cache_employe_ajax, name='invalider_cache_employe_ajax'),
    
    # Statut de synchronisation
    path('interim/ajax/statut-sync-employe/<str:matricule>/', views_employee_search.statut_sync_employe_ajax, name='statut_sync_employe_ajax'),
    
    # Synchronisation forcée
    path('interim/ajax/forcer-sync-kelio/', views_employee_search.forcer_sync_kelio_ajax, name='forcer_sync_kelio_ajax'),
    
    # Suggestions de matricules
    path('interim/ajax/suggestions-matricule/', views_employee_search.obtenir_suggestions_matricule_ajax, name='suggestions_matricule_ajax'),
    
    # Statistiques du cache
    path('ajax/statistiques-cache-employes/', views_employee_search.statistiques_cache_employes_ajax, name='statistiques_cache_employes_ajax'),

    # ================================================================
    # AJAX POUR PROPOSITION AUTOMATIQUE DE CANDIDATS (views.py)
    # ================================================================

    # Vue principale pour la proposition automatique
    path('interim/ajax/proposition-automatique/', 
      views.ajax_proposition_automatique, 
      name='ajax_proposition_automatique'),

    # Calcul de score pour un candidat spécifique
    path('interim/ajax/calculer-score-candidat/', 
      views.ajax_calculer_score_candidat, 
      name='ajax_calculer_score_candidat'),

    # Recherche de candidat alternatif
    path('interim/ajax/rechercher-candidat-alternatif/', 
         views.ajax_rechercher_candidat_alternatif, 
         name='ajax_rechercher_candidat_alternatif'),
    
    # Calcul de score pour candidat alternatif
    path('interim/ajax/calculer-score-alternatif/', 
         views.ajax_calculer_score_alternatif, 
         name='ajax_calculer_score_alternatif'),
    
    # Obtenir le score pour candidat pour une demande
    #path('interim/ajax/demande/<int:demande_id>/candidat/<int:candidat_id>/score', 
    #     views.ajax_get_score_candidat_demande, 
    #     name='ajax_get_score_candidat_demande'),
    

    # Validation rapide d'une proposition
    path('interim/ajax/validation-rapide/<int:demande_id>/', 
         views.ajax_validation_rapide, 
         name='ajax_validation_rapide'),
    
    # Vérification de cohérence du workflow
    path('interim/ajax/verifier-coherence-workflow/<int:demande_id>/', 
         views.ajax_verifier_coherence_workflow, 
         name='ajax_verifier_coherence_workflow'),
    
    # Prévisualisation d'une validation
    path('interim/ajax/previsualiser-validation/', 
         views.ajax_previsualiser_validation, 
         name='ajax_previsualiser_validation'),
    
    # Vérification de disponibilité candidat alternatif
    path('interim/ajax/verifier-disponibilite-alternatif/', 
         views.ajax_verifier_disponibilite_alternatif, 
         name='ajax_verifier_disponibilite_alternatif'),
    
    # Sauvegarde brouillon validation
    path('interim/ajax/sauvegarder-brouillon-validation/', 
         views.ajax_sauvegarder_brouillon_validation, 
         name='ajax_sauvegarder_brouillon_validation'),
    
    # Récupération détails proposition
    path('interim/ajax/details-proposition/<int:proposition_id>/', 
         views.ajax_details_proposition, 
         name='ajax_details_proposition'),
    
    # Score d'une proposition humaine spécifique
    path(
        'ajax/proposition/<int:proposition_id>/score-details/',
        views_ajax.proposition_score_details,
        name='proposition_score_details'
    ),
    
    # Score automatique d'un candidat par matricule
    path(
        'ajax/candidat/matricule/<str:candidat_matricule>/score-automatique/<int:demande_id>/',
        views_ajax.candidat_score_automatique_by_matricule,
        name='candidat_score_automatique_by_matricule'
    ),
    
    # Score détaillé général d'un candidat par matricule
    path(
        'ajax/candidat/matricule/<str:candidat_matricule>/score-details/<int:demande_id>/',
        views_ajax.candidat_score_details_by_matricule,
        name='candidat_score_details_by_matricule'
    ),
    
   path(
        'interim/ajax/proposition/<int:proposition_id>/score-details/',
        views_ajax.proposition_score_details,
        name='proposition_score_details'
    ),

    # ================================================================
    # RECHERCHE ET GESTION DES CANDIDATS
    # ================================================================
    
    # Recherche de candidat alternatif par matricule
    path(
        'ajax/rechercher-candidat-alternatif/',
        views_ajax.rechercher_candidat_alternatif,
        name='rechercher_candidat_alternatif'
    ),
    
    # ================================================================
    # ACTIONS DE WORKFLOW ET COMMUNICATION
    # ================================================================
    
    # Demande d'informations complémentaires
    path(
        'ajax/demander-informations/',
        views_ajax.demander_informations,
        name='demander_informations'
    ),
    
    # Escalade de validation
    path(
        'ajax/escalader-validation/',
        views_ajax.escalader_validation,
        name='escalader_validation'
    ),

    # ================================================================
    # API ENDPOINTS
    # ================================================================
      
    # === API DEMANDES ===
    path('interim/api/demandes/', views.api_demandes_list, name='api_demandes_list'),
    path('interim/api/demande/<int:pk>/', views.api_demande_detail, name='api_demande_detail'),
    # API WORKFLOW STATUS
    path('interim/api/workflow/status/<int:demande_id>/', views.api_workflow_status, name='api_workflow_status'),
    
    # === API EMPLOYÉS ===
    path('interim/api/employes/', views.api_employes_list, name='api_employes_list'),
    path('interim/api/employe/<str:matricule>/', views.api_employe_detail, name='api_employe_detail'),
    path('interim/api/employe/<int:candidat_id>/disponibilite/', views.api_candidat_disponibilite, name='api_candidat_disponibilite'),
       
    # === API KELIO ===
    path('interim/api/kelio/sync/<str:matricule>/', views.employe_sync_ajax, name='api_kelio_sync_employe'),
    path('interim/api/kelio/test-connexion/', views.kelio_test_connexion_ajax, name='api_kelio_test'),
    path('interim/api/kelio/vider-cache/', views.kelio_vider_cache_ajax, name='api_kelio_vider_cache'),
    path('interim/api/kelio/sync-global/', views.kelio_sync_global_ajax, name='api_kelio_sync_global'),
    path('interim/api/kelio/verification/<str:matricule>/', views.employe_verification_matricule_ajax, name='api_verification_matricule'),
    path('interim/api/kelio/creer-depuis-matricule/', views.employe_creer_depuis_matricule_ajax, name='api_creer_depuis_matricule'),
    
    # === API UTILITAIRES ===
    path('interim/api/candidat/disponibilite/', views.verifier_disponibilite_candidat_ajax, name='api_verifier_disponibilite'),
    path('interim/api/notifications/count/', views.notifications_count_ajax, name='notifications_count'),
    path('interim/api/notification/<int:notification_id>/lue/', views.marquer_notification_lue, name='notification_lue'),
    path('interim/api/notifications/toutes-lues/', views.marquer_toutes_lues, name='notifications_toutes_lues'),
    path('interim/api/refresh-stats/', views.refresh_stats_ajax, name='refresh_stats_ajax'),

    # Alternative avec interface dédiée
    path('interim/admin/kelio/sync-global/', views_kelio.ajax_update_kelio_global, name='admin_kelio_sync_global'),

    path('interim/admin/kelio/health-check-v43/', views_kelio.ajax_kelio_health_check_v43, name='kelio_health_check_v43'),
    path('interim/admin/kelio/sync-stats-v43/', views_kelio.ajax_kelio_sync_stats_v43, name='kelio_sync_stats_v43'),
    path('interim/admin/kelio/test-connection-v43/', views_kelio.ajax_test_kelio_connection_v43, name='kelio_test_connection_v43'),
    
    # ================================================================
    # WEBHOOKS (views.py)
    # ================================================================
    path('interim/webhook/kelio/employe/', views.webhook_kelio_employe, name='webhook_kelio_employe'),
    path('interim/webhook/kelio/absence/', views.webhook_kelio_absence, name='webhook_kelio_absence'),
    path('interim/webhook/kelio/competence/', views.webhook_kelio_competence, name='webhook_kelio_competence'),
    path('interim/webhook/notification/', views.webhook_notification, name='webhook_notification'),
    path('interim/webhook/validation/', views.webhook_validation, name='webhook_validation'),
    path('interim/webhook/rappel/', views.webhook_rappel, name='webhook_rappel'),
    
    # ================================================================
    # GESTION D'ERREURS (views.py)
    # ================================================================
    path('interim/erreur/403/', views.erreur_403_view, name='erreur_403'),
    path('interim/erreur/404/', views.erreur_404_view, name='erreur_404'),
    path('interim/erreur/500/', views.erreur_500_view, name='erreur_500'),
    
    # ================================================================
    # REDIRECTIONS POUR COMPATIBILITÉ
    # ================================================================
    path('interim/validation-detail/<int:demande_id>/', views_workflow_notif.validation_avec_propositions, name='legacy_validation_detail'),
    #path('interim/validation-drh/<int:demande_id>/', views_workflow_notif.validation_drh_dashboard, name='validation_drh_dashboard'),
    path('interim/reponse-interim/<int:demande_id>/', views_workflow_notif.reponse_candidat_view, name='legacy_reponse_interim'),
    path('interim/detail/<int:demande_id>/', views.demande_interim_detail_view, name='legacy_detail'),
    path('interim/suivi/<int:demande_id>/', views.workflow_detail_view, name='legacy_suivi'),

    # ================================================================
    # JOURS FÉRIÉS - API ET GESTION
    # ================================================================

    path('interim/jours-feries/', views_jours_feries.jourferie_liste, name='jourferie_liste'),
    path('interim/jours-feries/<int:pk>/', views_jours_feries.jourferie_afficher, name='jourferie_afficher'),
    path('interim/jours-feries/creer/', views_jours_feries.jourferie_creer, name='jourferie_creer'),
    path('interim/jours-feries/musulman/<int:pk>/modifier/', views_jours_feries.jourferiemusulman_modifier, name='jourferiemusulman_modifier'),
    path('interim/jours-feries/<int:pk>/supprimer/', views_jours_feries.jourferie_supprimer, name='jourferie_supprimer'),

    # API - Liste des fériés musulmans (pour le panneau admin)
    path('interim/api/feries-musulmans/', views_jours_feries.api_feries_musulmans, name='api_feries_musulmans'),
    
    # API - Liste des signalements en attente (admin)
    path('interim/api/signalements-feries/', views_jours_feries.api_signalements_feries, name='api_signalements_feries'),
    
    # Signaler une correction de date (utilisateurs)
    path('interim/feries/signaler-correction/', views_jours_feries.signaler_correction_ferie, name='signaler_correction_ferie'),
    
    # Traiter un signalement (admin)
    path('interim/feries/traiter-signalement/', views_jours_feries.traiter_signalement_ferie, name='traiter_signalement_ferie'),
    
    # Modifier la date d'un férié (admin)
    path('interim/feries/modifier-date/', views_jours_feries.modifier_date_ferie, name='modifier_date_ferie'),
    
    # Réinitialiser la date d'un férié (admin)
    path('interim/feries/reinitialiser-date/', views_jours_feries.reinitialiser_date_ferie, name='reinitialiser_date_ferie'),

    # Liste des absences avec filtres et jours fériés
    path('interim/extraction/', views_absences_extraction.absences_extraction_liste, name='absences_extraction_liste'),
    
    # Export (PDF, XLSX, CSV)
    path('interim/extraction/export/<str:format_export>/', views_absences_extraction.absences_extraction_export, name='absences_extraction_export'),
    
    # API JSON
    path('interim/api/extraction/', views_absences_extraction.api_absences_extraction, name='api_absences_extraction'),
]

# Gestion des fichiers statiques en développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# ================================================================
# DOCUMENTATION DES URLS DISPONIBLES
# ================================================================

"""
# Suggestions de candidats basées sur l'IA
path('interim/ajax/suggestions-candidats/', 
     views.ajax_suggestions_candidats_intelligentes, 
     name='ajax_suggestions_candidats'),

# Validation en temps réel des données du formulaire
path('interim/ajax/valider-formulaire/', 
     views.ajax_valider_formulaire_interim, 
     name='ajax_valider_formulaire'),

Ce fichier urls.py consolidé contient uniquement les patterns correspondant
aux vues réellement implémentées dans les fichiers fournis :

- views.py : Vues principales du système d'intérim
- views_auth.py : Authentification et dashboards hiérarchiques  
- views_manager_proposals.py : Propositions managériales
- views_workflow_notif.py : Workflow et notifications

STRUCTURE DES URLS :

1. AUTHENTIFICATION :
   - /connexion/ : Connexion utilisateur
   - /deconnexion/ : Déconnexion
   
2. DASHBOARDS HIÉRARCHIQUES :
   - / : Dashboard chef d'équipe
   - /n1/ : Dashboard responsable N+1
   - /n2/ : Dashboard directeur N+2
   - /n3/ : Dashboard global RH/Admin
   
3. GESTION DES DEMANDES :
   - /interim/demande/ : Création/gestion demandes
   - /interim/mes-demandes/ : Mes demandes
   - /interim/recherche/ : Recherche candidats
   - /interim/selection/ : Sélection candidats
   
4. WORKFLOW ET VALIDATIONS :
   - /interim/validation/ : Validations standards
   - /interim/chef-service/ : Dashboard chef service
   - /interim/validation-n1/ : Dashboard validation N+1
   - /interim/validation-drh/ : Dashboard validation DRH
   
5. PROPOSITIONS MANAGÉRIALES :
   - /interim/proposer/ : Proposer candidats
   - /interim/mes-propositions/ : Mes propositions
   - /interim/manager/propositions/ : Dashboard propositions
   
6. API ENDPOINTS :
   - /interim/api/demandes/ : API demandes
   - /interim/api/employes/ : API employés
   - /interim/api/stats/ : API statistiques
   - /interim/api/workflow/ : API workflow
   - /interim/api/propositions/ : API propositions

Toutes les URLs listées correspondent à des vues existantes et fonctionnelles.
"""