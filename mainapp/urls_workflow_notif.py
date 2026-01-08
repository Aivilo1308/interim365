# urls.py - URLs étendues pour le workflow d'intérim

from django.urls import path
from . import views

urlpatterns = [
    # URLs existantes
    path('', views.index, name='index'),
    path('demande/', views.interim_demande, name='interim_demande'),
    path('recherche/', views.interim_recherche, name='interim_recherche'),
    #path('validation/', views.interim_validation, name='interim_validation'),
    path('historique/', views.historique_interim, name='historique_interim'),
    path('selection/', views.interim_selection, name='interim_selection'),
    path('stats/', views.interim_stats, name='interim_stats'),
    path('notes/', views.interim_notes, name='interim_notes'),
    
    # === NOUVELLES URLs POUR LE WORKFLOW ===
    
    # Gestion des candidats
    path('proposer-candidat/<int:demande_id>/', views.proposer_candidat_view, name='proposer_candidat'),
    path('reponse-candidat/<int:demande_id>/', views.reponse_candidat_view, name='reponse_candidat'),
    
    # Actions de validation
    path('valider-n1/<int:demande_id>/', views.valider_n1, name='valider_n1'),
    path('valider-drh/<int:demande_id>/', views.valider_drh, name='valider_drh'),
    
    # Gestion des notifications
    path('notifications/', views.mes_notifications, name='mes_notifications'),
    path('notification/<int:notification_id>/traiter/', views.marquer_notification_traitee, name='marquer_notification_traitee'),
    
    # Vues détaillées
    #path('demande/<int:demande_id>/detail/', views.demande_detail_view, name='demande_detail'),
    path('demande/<int:demande_id>/workflow/', views.workflow_detail_view, name='workflow_detail'),
    path('validation/<int:demande_id>/detail/', views.validation_detail_view, name='validation_detail'),
    
    # === API ENDPOINTS ===
    
    # APIs pour les données temps réel
    path('api/notifications/count/', views.api_notifications_count, name='api_notifications_count'),
    path('api/workflow/status/<int:demande_id>/', views.api_workflow_status, name='api_workflow_status'),
    path('api/candidats/recherche/', views.api_recherche_candidats, name='api_recherche_candidats'),
    path('api/candidat/<int:candidat_id>/disponibilite/', views.api_candidat_disponibilite, name='api_candidat_disponibilite'),
    
    # APIs pour les actions AJAX
    path('api/demande/<int:demande_id>/proposer-candidat/', views.api_proposer_candidat, name='api_proposer_candidat'),
    path('api/validation/<int:validation_id>/traiter/', views.api_traiter_validation, name='api_traiter_validation'),
    path('api/notification/<int:notification_id>/marquer-lue/', views.api_marquer_notification_lue, name='api_marquer_notification_lue'),
    
    # APIs pour les statistiques
    path('api/stats/chef-service/', views.api_stats_chef_service, name='api_stats_chef_service'),
    path('api/stats/validations/', views.api_stats_validations, name='api_stats_validations'),
    path('api/stats/drh/', views.api_stats_drh, name='api_stats_drh'),
    
    # === VUES D'ADMINISTRATION ===
    
    # Configuration du workflow
    path('admin/workflow/etapes/', views.admin_workflow_etapes, name='admin_workflow_etapes'),
    path('admin/workflow/etape/<int:etape_id>/modifier/', views.admin_modifier_etape, name='admin_modifier_etape'),
    path('admin/workflow/notifications/', views.admin_notifications_config, name='admin_notifications_config'),
    
    # Suivi et monitoring
    path('admin/workflow/monitoring/', views.admin_workflow_monitoring, name='admin_workflow_monitoring'),
    path('admin/notifications/historique/', views.admin_notifications_historique, name='admin_notifications_historique'),
    path('admin/validations/rapport/', views.admin_rapport_validations, name='admin_rapport_validations'),
    
    # === VUES DE RAPPORTS ===
    
    # Rapports pour les managers
    path('rapports/validations/', views.rapport_validations, name='rapport_validations'),
    path('rapports/candidats/', views.rapport_candidats, name='rapport_candidats'),
    path('rapports/workflow/', views.rapport_workflow, name='rapport_workflow'),
    
    # Export de données
    path('export/demandes/', views.export_demandes, name='export_demandes'),
    path('export/validations/', views.export_validations, name='export_validations'),
    path('export/notifications/', views.export_notifications, name='export_notifications'),
    
    # === VUES UTILITAIRES ===
    
    # Recherche et filtres
    path('recherche/demandes/', views.recherche_demandes, name='recherche_demandes'),
    path('recherche/candidats/', views.recherche_candidats_avancee, name='recherche_candidats_avancee'),
    path('filtre/notifications/', views.filtre_notifications, name='filtre_notifications'),
    
    # Actions en lot
    path('actions/notifications/marquer-toutes-lues/', views.marquer_toutes_notifications_lues, name='marquer_toutes_notifications_lues'),
    path('actions/validations/rappels/', views.envoyer_rappels_validations, name='envoyer_rappels_validations'),
    
    # === VUES SPÉCIALISÉES PAR RÔLE ===
    
    # Vues pour les employés standard
    path('employe/mes-demandes/', views.employe_mes_demandes, name='employe_mes_demandes'),
    path('employe/mes-missions/', views.employe_mes_missions, name='employe_mes_missions'),
    path('employe/disponibilites/', views.employe_disponibilites, name='employe_disponibilites'),
    
    # Vues pour les managers
    path('manager/equipe/', views.manager_gestion_equipe, name='manager_gestion_equipe'),
    path('manager/validations/', views.manager_mes_validations, name='manager_mes_validations'),
    path('manager/stats/', views.manager_statistiques, name='manager_statistiques'),
    
    # Vues pour la DRH
    path('drh/tableau-bord/', views.drh_tableau_bord, name='drh_tableau_bord'),
    path('drh/gestion-workflow/', views.drh_gestion_workflow, name='drh_gestion_workflow'),
    path('drh/rapports-globaux/', views.drh_rapports_globaux, name='drh_rapports_globaux'),
    
    # === URLs POUR LES WEBHOOKS (OPTIONNEL) ===
    
    # Webhooks pour intégrations externes
    path('webhook/notification/', views.webhook_notification, name='webhook_notification'),
    path('webhook/validation/', views.webhook_validation, name='webhook_validation'),
    path('webhook/rappel/', views.webhook_rappel, name='webhook_rappel'),
    
    # === URLs POUR LA DOCUMENTATION ET L'AIDE ===
    
    # Documentation du workflow
    path('aide/workflow/', views.aide_workflow, name='aide_workflow'),
    path('aide/notifications/', views.aide_notifications, name='aide_notifications'),
    path('aide/validations/', views.aide_validations, name='aide_validations'),
    
    # Tutoriels interactifs
    path('tutoriel/chef-service/', views.tutoriel_chef_service, name='tutoriel_chef_service'),
    path('tutoriel/validateur/', views.tutoriel_validateur, name='tutoriel_validateur'),
    path('tutoriel/candidat/', views.tutoriel_candidat, name='tutoriel_candidat'),
]

# === PATTERNS DE REDIRECTION ===

# Redirections pour compatibilité
workflow_redirects = [
    # Anciennes URLs vers nouvelles URLs
    path('validation-detail/<int:demande_id>/', views.validation_detail_view, name='interim_validation_detail'),
    #path('validation-drh/<int:demande_id>/', views.validation_drh_dashboard, name='validation_drh_dashboard'),
    path('reponse-interim/<int:demande_id>/', views.reponse_candidat_view, name='interim_reponse_candidat'),
    path('detail/<int:demande_id>/', views.demande_detail_view, name='interim_detail'),
    path('suivi/<int:demande_id>/', views.workflow_detail_view, name='interim_suivi'),
]

# Ajouter les redirections aux URLs principales
urlpatterns += workflow_redirects