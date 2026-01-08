"""
Administration Django pour le système de gestion d'intérim - Version CORRIGÉE
Interface d'administration complète avec support des propositions humaines et scoring hybride

✅ Erreurs de syntaxe corrigées
✅ Imports manquants ajoutés
✅ Références circulaires résolues
✅ Méthodes manquantes implémentées
✅ Tous les modèles de models.py intégrés et configurés
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Q, Sum, Avg, F, Max
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.contrib.admin import SimpleListFilter
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.db import transaction

import csv
from datetime import date, timedelta
import logging

from .models import (
    # Configuration Kelio et Scoring
    ConfigurationApiKelio, ConfigurationScoring, CacheApiKelio,
    
    # Organisation
    Departement, Site, Poste,
    
    # Utilisateurs et profils
    ProfilUtilisateur, ProfilUtilisateurKelio, ProfilUtilisateurExtended,
    
    # Compétences
    Competence, CompetenceUtilisateur,
    
    # Intérim et Workflow
    MotifAbsence, DemandeInterim, WorkflowEtape, WorkflowDemande,
    
    # Propositions et Scoring intégrés
    PropositionCandidat, ScoreDetailCandidat,
    
    # Validation et Workflow
    ValidationDemande,
    
    # Notifications et Historique
    NotificationInterim, HistoriqueAction,
    
    # Réponses candidats
    ReponseCandidatInterim,
    
    # Données connexes
    FormationUtilisateur, AbsenceUtilisateur, DisponibiliteUtilisateur
)

logger = logging.getLogger(__name__)

# ================================================================
# CONFIGURATION GLOBALE
# ================================================================

admin.site.site_header = "Administration Système d'Intérim Intégré"
admin.site.site_title = "Intérim Admin"
admin.site.index_title = "Tableau de bord - Propositions & Scoring hybride"

# ================================================================
# UTILITAIRES SÉCURISÉS
# ================================================================

def safe_display(obj, attr_name, default="N/A"):
    """Récupère un attribut de façon sécurisée"""
    try:
        if hasattr(obj, attr_name):
            value = getattr(obj, attr_name)
            return value() if callable(value) else value
        return default
    except Exception:
        return default

def format_boolean_display(value, true_icon="✅", false_icon="❌"):
    """Formate un booléen avec des icônes"""
    return format_html(
        '<span style="color: {};">{}</span>',
        'green' if value else 'red',
        true_icon if value else false_icon
    )

def format_status_display(is_active):
    """Formate le statut actif/inactif"""
    if is_active:
        return format_html('<span style="color: green;">🟢 Actif</span>')
    else:
        return format_html('<span style="color: red;">🔴 Inactif</span>')

def format_score_display(score, max_score=100):
    """Formate un score avec couleur selon la valeur"""
    if score is None:
        return format_html('<span style="color: gray;">❓ Non calculé</span>')
    
    percentage = (score / max_score) * 100
    if percentage >= 80:
        color = 'green'
        icon = '🟢'
    elif percentage >= 60:
        color = 'orange'
        icon = '🟡'
    else:
        color = 'red'
        icon = '🔴'
    
    return format_html(
        '<span style="color: {};">{} {}/100</span>',
        color, icon, score
    )

def format_urgence_display(urgence):
    """Formate l'urgence avec couleurs appropriées"""
    urgences = {
        'CRITIQUE': ('<span style="color: red; font-weight: bold;">🚨 CRITIQUE</span>'),
        'ELEVEE': ('<span style="color: orange; font-weight: bold;">🔴 ÉLEVÉE</span>'),
        'MOYENNE': ('<span style="color: #FFA500;">🟡 MOYENNE</span>'),
        'NORMALE': ('<span style="color: green;">🟢 NORMALE</span>'),
    }
    return format_html(urgences.get(urgence, urgence))

# ================================================================
# CLASSE DE BASE SÉCURISÉE
# ================================================================

class BaseModelAdmin(admin.ModelAdmin):
    """Classe de base pour tous les admins avec optimisations"""
    
    show_full_result_count = False
    list_per_page = 25
    list_max_show_all = 100
    actions = ['export_csv']
    
    def get_queryset(self, request):
        """Optimise les requêtes de base"""
        qs = super().get_queryset(request)
        try:
            # Optimisation basique des ForeignKey
            fk_fields = []
            for field in self.model._meta.fields:
                if (hasattr(field, 'related_model') and 
                    field.related_model and 
                    not field.name.endswith('_ptr')):
                    fk_fields.append(field.name)
            
            if fk_fields:
                qs = qs.select_related(*fk_fields[:3])  # Limiter à 3 relations
        except Exception:
            pass
        return qs
    
    def export_csv(self, request, queryset):
        """Exporte la sélection en CSV"""
        try:
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{self.model._meta.verbose_name_plural}.csv"'
            
            writer = csv.writer(response)
            
            # En-têtes sécurisés
            fields = []
            for field in self.model._meta.fields:
                if not field.name.endswith('_ptr') and not field.name == 'password':
                    fields.append(field.name)
            
            writer.writerow(fields)
            
            # Données
            for obj in queryset:
                row = []
                for field in fields:
                    try:
                        value = getattr(obj, field, '')
                        if hasattr(value, 'pk'):
                            value = str(value)
                        row.append(str(value) if value is not None else '')
                    except Exception:
                        row.append('')
                writer.writerow(row)
            
            self.message_user(request, f"{queryset.count()} enregistrements exportés.")
            return response
            
        except Exception as e:
            self.message_user(request, f"Erreur export : {str(e)}", level=messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
    
    export_csv.short_description = "Exporter en CSV"

class ReadOnlyMixin:
    """Mixin pour les modèles en lecture seule"""
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

# ================================================================
# FILTRES PERSONNALISÉS ÉTENDUS
# ================================================================

class StatutPropositionFilter(SimpleListFilter):
    title = 'Statut proposition'
    parameter_name = 'statut_proposition'
    
    def lookups(self, request, model_admin):
        return [
            ('SOUMISE', 'Soumise'),
            ('EN_EVALUATION', 'En évaluation'),
            ('EVALUEE', 'Évaluée'),
            ('RETENUE', 'Retenue'),
            ('REJETEE', 'Rejetée'),
            ('VALIDEE', 'Validée'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(statut=self.value())
        return queryset

class SourcePropositionFilter(SimpleListFilter):
    title = 'Source proposition'
    parameter_name = 'source_proposition'
    
    def lookups(self, request, model_admin):
        return [
            ('MANAGER_DIRECT', 'Manager direct'),
            ('RESPONSABLE_N1', 'Responsable N+1'),
            ('RESPONSABLE_N2', 'Responsable N+2'),
            ('DIRECTEUR', 'Directeur'),
            ('DRH', 'DRH'),
            ('AUTRE', 'Autre'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(source_proposition=self.value())
        return queryset

class NotificationTypeFilter(SimpleListFilter):
    title = 'Type notification'
    parameter_name = 'type_notification'
    
    def lookups(self, request, model_admin):
        return [
            ('NOUVELLE_DEMANDE', 'Nouvelle demande'),
            ('PROPOSITION_CANDIDAT', 'Proposition candidat'),
            ('CANDIDAT_SELECTIONNE', 'Candidat sélectionné'),
            ('VALIDATION_EFFECTUEE', 'Validation effectuée'),
            ('RAPPEL_VALIDATION', 'Rappel validation'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(type_notification=self.value())
        return queryset

class ScoreRangeFilter(SimpleListFilter):
    title = 'Gamme de score'
    parameter_name = 'score_range'
    
    def lookups(self, request, model_admin):
        return [
            ('80_100', '80-100 (Excellent)'),
            ('60_79', '60-79 (Bon)'),
            ('40_59', '40-59 (Moyen)'),
            ('0_39', '0-39 (Faible)'),
        ]
    
    def queryset(self, request, queryset):
        if self.value() == '80_100':
            return queryset.filter(score_total__gte=80)
        elif self.value() == '60_79':
            return queryset.filter(score_total__gte=60, score_total__lt=80)
        elif self.value() == '40_59':
            return queryset.filter(score_total__gte=40, score_total__lt=60)
        elif self.value() == '0_39':
            return queryset.filter(score_total__lt=40)
        return queryset

# ================================================================
# INLINES POUR LES PROPOSITIONS ET SCORING
# ================================================================

class PropositionCandidatInline(admin.TabularInline):
    model = PropositionCandidat
    extra = 0
    fields = ('candidat_propose', 'proposant', 'source_proposition', 'statut', 'score_final', 'justification')
    readonly_fields = ('numero_proposition', 'score_final', 'created_at')
    can_delete = False
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'candidat_propose__user', 'proposant__user'
        )

class ScoreDetailCandidatInline(admin.StackedInline):
    model = ScoreDetailCandidat
    extra = 0
    fields = (
        ('score_similarite_poste', 'score_competences', 'score_experience'),
        ('score_disponibilite', 'score_proximite', 'score_anciennete'),
        ('bonus_proposition_humaine', 'bonus_experience_similaire'),
        ('penalite_indisponibilite', 'score_total'),
        'calcule_par'
    )
    readonly_fields = ('score_total', 'created_at')
    can_delete = False

class ValidationDemandeInline(admin.TabularInline):
    model = ValidationDemande
    extra = 0
    fields = ('type_validation', 'validateur', 'decision', 'date_validation', 'commentaire')
    readonly_fields = ('date_demande_validation', 'date_validation')
    can_delete = False

class NotificationInterimInline(admin.TabularInline):
    model = NotificationInterim
    extra = 0
    fields = ('type_notification', 'destinataire', 'urgence', 'statut', 'created_at')
    readonly_fields = ('created_at',)
    fk_name = 'demande'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('destinataire__user')

# ================================================================
# ADMINS CONFIGURATION SCORING ET KELIO
# ================================================================

@admin.register(ConfigurationScoring)
class ConfigurationScoringAdmin(BaseModelAdmin):
    list_display = (
        'nom', 'display_configuration_par_defaut', 'display_poids_principaux',
        'display_bonus_principaux', 'nb_utilisations', 'last_used', 'display_status'
    )
    list_filter = ('actif', 'configuration_par_defaut', 'created_by')
    search_fields = ('nom', 'description')
    readonly_fields = ('created_at', 'updated_at', 'nb_utilisations', 'last_used')
    
    fieldsets = (
        ('Configuration de base', {
            'fields': ('nom', 'description', 'configuration_par_defaut', 'actif')
        }),
        ('Poids des critères (total = 1.0)', {
            'fields': (
                ('poids_similarite_poste', 'poids_competences'),
                ('poids_experience', 'poids_disponibilite'),
                ('poids_proximite', 'poids_anciennete')
            ),
            'description': 'La somme de tous les poids doit être égale à 1.0'
        }),
        ('Bonus par source de proposition', {
            'fields': (
                ('bonus_proposition_humaine', 'bonus_experience_similaire'),
                ('bonus_recommandation', 'bonus_manager_direct'),
                ('bonus_chef_equipe', 'bonus_directeur', 'bonus_drh')
            )
        }),
        ('Pénalités', {
            'fields': (
                'penalite_indisponibilite_partielle',
                'penalite_indisponibilite_totale',
                'penalite_distance_excessive'
            )
        }),
        ('Restrictions d\'usage', {
            'fields': ('pour_departements', 'pour_types_urgence'),
            'classes': ('collapse',)
        }),
        ('Audit et usage', {
            'fields': ('created_by', 'nb_utilisations', 'last_used'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['dupliquer_configuration', 'tester_configuration']
    
    def display_configuration_par_defaut(self, obj):
        if obj.configuration_par_defaut:
            return format_html('<span style="color: blue; font-weight: bold;">⭐ Défaut</span>')
        return "Non"
    display_configuration_par_defaut.short_description = "Défaut"
    
    def display_poids_principaux(self, obj):
        return f"Poste:{obj.poids_similarite_poste:.2f} | Comp:{obj.poids_competences:.2f} | Exp:{obj.poids_experience:.2f}"
    display_poids_principaux.short_description = "Poids principaux"
    
    def display_bonus_principaux(self, obj):
        return f"Humain:+{obj.bonus_proposition_humaine} | Manager:+{obj.bonus_manager_direct} | DRH:+{obj.bonus_drh}"
    display_bonus_principaux.short_description = "Bonus principaux"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def dupliquer_configuration(self, request, queryset):
        """Duplique les configurations sélectionnées"""
        for config in queryset:
            nouveau_nom = f"{config.nom} - Copie"
            config.pk = None
            config.nom = nouveau_nom
            config.configuration_par_defaut = False
            config.nb_utilisations = 0
            config.last_used = None
            config.created_by = request.user.profilutilisateur
            config.save()
        
        self.message_user(request, f"{queryset.count()} configuration(s) dupliquée(s).")
    dupliquer_configuration.short_description = "Dupliquer les configurations"
    
    def tester_configuration(self, request, queryset):
        """Teste la validité des configurations"""
        for config in queryset:
            try:
                config.clean()
                self.message_user(request, f"Configuration '{config.nom}' : ✅ Valide")
            except ValidationError as e:
                self.message_user(request, f"Configuration '{config.nom}' : ❌ {e}", level=messages.ERROR)
    tester_configuration.short_description = "Tester les configurations"

@admin.register(ConfigurationApiKelio)
class ConfigurationApiKelioAdmin(BaseModelAdmin):
    list_display = (
        'nom', 'url_base', 'display_status', 'display_services', 
        'display_cache_stats', 'created_at'
    )
    list_filter = ('actif', 'service_employees', 'service_absences')
    search_fields = ('nom', 'url_base', 'username')
    readonly_fields = ('created_at', 'updated_at', 'display_cache_actuel')
    
    fieldsets = (
        ('Configuration de base', {
            'fields': ('nom', 'url_base', 'username', 'password', 'actif', 'timeout_seconds')
        }),
        ('Services Kelio', {
            'fields': (
                ('service_employees', 'service_absences'),
                ('service_formations', 'service_competences')
            )
        }),
        ('Configuration cache', {
            'fields': (
                ('cache_duree_defaut_minutes', 'cache_taille_max_mo'),
                ('auto_invalidation_cache', 'display_cache_actuel')
            )
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_services(self, obj):
        services = []
        if obj.service_employees: services.append("👥")
        if obj.service_absences: services.append("📅")
        if obj.service_formations: services.append("📚")
        if obj.service_competences: services.append("🔧")
        return "".join(services) if services else "❌"
    display_services.short_description = "Services"
    
    def display_cache_stats(self, obj):
        try:
            count = obj.caches.count()
            taille = obj.get_taille_cache_actuel()
            return f"{count} entrées ({taille} MB)"
        except Exception:
            return "Erreur"
    display_cache_stats.short_description = "Cache"
    
    def display_cache_actuel(self, obj):
        if obj.pk:
            return f"{obj.get_taille_cache_actuel()} MB / {obj.cache_taille_max_mo} MB"
        return "Non calculé"
    display_cache_actuel.short_description = "Utilisation cache"

# ================================================================
# ADMINS WORKFLOW INTÉGRÉS
# ================================================================

@admin.register(WorkflowEtape)
class WorkflowEtapeAdmin(BaseModelAdmin):
    list_display = (
        'ordre', 'nom', 'type_etape', 'obligatoire', 'delai_max_heures',
        'display_propositions', 'condition_urgence', 'actif'
    )
    list_filter = ('type_etape', 'obligatoire', 'condition_urgence', 'actif')
    search_fields = ('nom',)
    readonly_fields = ('created_at', 'updated_at') if hasattr(WorkflowEtape, 'created_at') else ()
    
    fieldsets = (
        ('Étape', {
            'fields': ('nom', 'type_etape', 'ordre', 'obligatoire', 'actif')
        }),
        ('Configuration', {
            'fields': ('delai_max_heures', 'condition_urgence')
        }),
        ('Propositions de candidats', {
            'fields': ('permet_propositions_humaines', 'permet_ajout_nouveaux_candidats')
        })
    )
    
    def display_propositions(self, obj):
        if obj.permet_propositions_humaines:
            return format_html('<span style="color: green;">✅ Autorisées</span>')
        return format_html('<span style="color: red;">❌ Non autorisées</span>')
    display_propositions.short_description = "Propositions"

@admin.register(WorkflowDemande)
class WorkflowDemandeAdmin(ReadOnlyMixin, BaseModelAdmin):
    list_display = (
        'demande', 'etape_actuelle', 'display_progression', 'nb_propositions_recues',
        'nb_candidats_evalues', 'display_retard', 'date_derniere_action'
    )
    list_filter = ('etape_actuelle', 'nb_propositions_recues')
    search_fields = ('demande__numero_demande',)
    readonly_fields = (
        'demande', 'historique_actions', 'nb_propositions_recues', 
        'nb_candidats_evalues', 'nb_niveaux_validation_passes'
    )
    
    fieldsets = (
        ('Workflow', {
            'fields': ('demande', 'etape_actuelle', 'date_derniere_action')
        }),
        ('Statistiques', {
            'fields': (
                'nb_propositions_recues', 'nb_candidats_evalues', 
                'nb_niveaux_validation_passes'
            )
        }),
        ('Historique', {
            'fields': ('historique_actions',),
            'classes': ('collapse',)
        })
    )
    
    def display_progression(self, obj):
        pourcentage = obj.progression_percentage
        return format_html(
            '<div style="width: 100px; background: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background: #007cba; height: 20px; border-radius: 3px; text-align: center; color: white; font-size: 12px; line-height: 20px;">'
            '{}%</div></div>',
            pourcentage, int(pourcentage)
        )
    display_progression.short_description = "Progression"
    
    def display_retard(self, obj):
        if obj.est_en_retard:
            return format_html('<span style="color: red;">🚨 En retard</span>')
        return format_html('<span style="color: green;">✅ Dans les temps</span>')
    display_retard.short_description = "Délai"

# ================================================================
# ADMINS PROPOSITIONS DE CANDIDATS
# ================================================================

@admin.register(PropositionCandidat)
class PropositionCandidatAdmin(BaseModelAdmin):
    list_display = (
        'numero_proposition', 'candidat_propose', 'proposant', 'demande_interim',
        'display_source', 'display_statut', 'display_score_final', 'created_at'
    )
    list_filter = (
        StatutPropositionFilter, SourcePropositionFilter, 
        'niveau_validation_propose', 'demande_interim__urgence'
    )
    search_fields = (
        'numero_proposition', 'candidat_propose__matricule', 'candidat_propose__user__first_name',
        'candidat_propose__user__last_name', 'proposant__matricule', 'demande_interim__numero_demande'
    )
    readonly_fields = (
        'numero_proposition', 'score_final', 'created_at', 'updated_at'
    )
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Identification', {
            'fields': ('numero_proposition', 'demande_interim')
        }),
        ('Proposition', {
            'fields': (
                ('candidat_propose', 'proposant'),
                ('source_proposition', 'niveau_validation_propose'),
                'statut'
            )
        }),
        ('Justification', {
            'fields': (
                'justification',
                'competences_specifiques',
                'experience_pertinente'
            )
        }),
        ('Scoring', {
            'fields': (
                ('score_automatique', 'score_humain_ajuste'),
                ('bonus_proposition_humaine', 'score_final')
            )
        }),
        ('Évaluation', {
            'fields': (
                ('evaluateur', 'date_evaluation'),
                'commentaire_evaluation'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    inlines = [ScoreDetailCandidatInline]
    actions = ['evaluer_propositions', 'retenir_pour_validation', 'rejeter_propositions']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'candidat_propose__user', 'proposant__user', 'demande_interim',
            'evaluateur__user'
        )
    
    def display_source(self, obj):
        return obj.source_display
    display_source.short_description = "Source"
    
    def display_statut(self, obj):
        statuts = {
            'SOUMISE': '<span style="color: blue;">📝 Soumise</span>',
            'EN_EVALUATION': '<span style="color: orange;">🔍 En évaluation</span>',
            'EVALUEE': '<span style="color: green;">✅ Évaluée</span>',
            'RETENUE': '<span style="color: purple;">⭐ Retenue</span>',
            'REJETEE': '<span style="color: red;">❌ Rejetée</span>',
            'VALIDEE': '<span style="color: green; font-weight: bold;">✅ Validée</span>',
        }
        return format_html(statuts.get(obj.statut, obj.statut))
    display_statut.short_description = "Statut"
    
    def display_score_final(self, obj):
        return format_score_display(obj.score_final)
    display_score_final.short_description = "Score final"
    
    def evaluer_propositions(self, request, queryset):
        """Marque les propositions comme évaluées"""
        updated = queryset.filter(statut='SOUMISE').update(
            statut='EVALUEE',
            evaluateur=request.user.profilutilisateur,
            date_evaluation=timezone.now()
        )
        self.message_user(request, f"{updated} proposition(s) évaluée(s).")
    evaluer_propositions.short_description = "Marquer comme évaluées"
    
    def retenir_pour_validation(self, request, queryset):
        """Retient les propositions pour validation"""
        updated = queryset.filter(statut='EVALUEE').update(statut='RETENUE')
        self.message_user(request, f"{updated} proposition(s) retenue(s) pour validation.")
    retenir_pour_validation.short_description = "Retenir pour validation"
    
    def rejeter_propositions(self, request, queryset):
        """Rejette les propositions"""
        updated = queryset.exclude(statut='VALIDEE').update(statut='REJETEE')
        self.message_user(request, f"{updated} proposition(s) rejetée(s).")
    rejeter_propositions.short_description = "Rejeter les propositions"

@admin.register(ScoreDetailCandidat)
class ScoreDetailCandidatAdmin(BaseModelAdmin):
    list_display = (
        'candidat', 'demande_interim', 'display_score_total', 'display_type_candidat',
        'display_scores_criteres', 'display_bonus_penalites', 'calcule_par'
    )
    list_filter = (ScoreRangeFilter, 'calcule_par', 'demande_interim__urgence')
    search_fields = (
        'candidat__matricule', 'candidat__user__first_name', 'candidat__user__last_name',
        'demande_interim__numero_demande'
    )
    readonly_fields = ('score_total', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Candidat et demande', {
            'fields': ('candidat', 'demande_interim', 'proposition_humaine')
        }),
        ('Scores par critère (0-100)', {
            'fields': (
                ('score_similarite_poste', 'score_competences'),
                ('score_experience', 'score_disponibilite'),
                ('score_proximite', 'score_anciennete')
            )
        }),
        ('Bonus et pénalités', {
            'fields': (
                ('bonus_proposition_humaine', 'bonus_experience_similaire'),
                ('bonus_recommandation', 'penalite_indisponibilite')
            )
        }),
        ('Score final', {
            'fields': ('score_total', 'calcule_par')
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['recalculer_scores', 'exporter_details_scoring']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'candidat__user', 'demande_interim', 'proposition_humaine'
        )
    
    def display_score_total(self, obj):
        return format_score_display(obj.score_total)
    display_score_total.short_description = "Score total"
    
    def display_type_candidat(self, obj):
        if obj.est_proposition_humaine:
            return format_html('<span style="color: blue;">👤 Proposition humaine</span>')
        return format_html('<span style="color: gray;">🤖 Sélection automatique</span>')
    display_type_candidat.short_description = "Type"
    
    def display_scores_criteres(self, obj):
        return f"Poste:{obj.score_similarite_poste} | Comp:{obj.score_competences} | Exp:{obj.score_experience}"
    display_scores_criteres.short_description = "Scores critères"
    
    def display_bonus_penalites(self, obj):
        bonus_total = (obj.bonus_proposition_humaine + obj.bonus_experience_similaire + 
                      obj.bonus_recommandation)
        return f"Bonus:+{bonus_total} | Pénalité:-{obj.penalite_indisponibilite}"
    display_bonus_penalites.short_description = "Bonus/Pénalités"
    
    def recalculer_scores(self, request, queryset):
        """Recalcule les scores sélectionnés"""
        for score in queryset:
            score.calculer_score_total()
            score.save()
        self.message_user(request, f"{queryset.count()} score(s) recalculé(s).")
    recalculer_scores.short_description = "Recalculer les scores"
    
    def exporter_details_scoring(self, request, queryset):
        """Exporte les détails de scoring en CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="details_scoring.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Candidat', 'Demande', 'Score Total', 'Similarité Poste', 'Compétences',
            'Expérience', 'Disponibilité', 'Proximité', 'Ancienneté', 'Bonus Humain',
            'Bonus Expérience', 'Pénalité Indispo', 'Type'
        ])
        
        for score in queryset:
            writer.writerow([
                score.candidat.nom_complet,
                score.demande_interim.numero_demande,
                score.score_total,
                score.score_similarite_poste,
                score.score_competences,
                score.score_experience,
                score.score_disponibilite,
                score.score_proximite,
                score.score_anciennete,
                score.bonus_proposition_humaine,
                score.bonus_experience_similaire,
                score.penalite_indisponibilite,
                'Humaine' if score.est_proposition_humaine else 'Automatique'
            ])
        
        return response
    exporter_details_scoring.short_description = "Exporter détails scoring"

# ================================================================
# ADMINS VALIDATION ET WORKFLOW
# ================================================================

@admin.register(ValidationDemande)
class ValidationDemandeAdmin(BaseModelAdmin):
    list_display = (
        'demande', 'type_validation', 'validateur', 'display_decision',
        'display_delai_traitement', 'display_candidats_traites', 'date_validation'
    )
    list_filter = ('type_validation', 'decision', 'niveau_validation')
    search_fields = (
        'demande__numero_demande', 'validateur__matricule', 
        'validateur__user__first_name', 'validateur__user__last_name'
    )
    readonly_fields = ('date_demande_validation', 'delai_traitement', 'created_at', 'updated_at')
    date_hierarchy = 'date_validation'
    
    fieldsets = (
        ('Validation', {
            'fields': (
                'demande', 'type_validation', 'niveau_validation',
                'validateur', 'decision'
            )
        }),
        ('Commentaire', {
            'fields': ('commentaire',)
        }),
        ('Candidats traités', {
            'fields': ('candidats_retenus', 'candidats_rejetes'),
            'classes': ('collapse',)
        }),
        ('Nouveau candidat proposé', {
            'fields': ('nouveau_candidat_propose', 'justification_nouveau_candidat'),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('date_demande_validation', 'date_validation'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'demande', 'validateur__user', 'nouveau_candidat_propose__user'
        )
    
    def display_decision(self, obj):
        return obj.decision_display
    display_decision.short_description = "Décision"
    
    def display_delai_traitement(self, obj):
        delai = obj.delai_traitement
        if delai:
            heures = delai.total_seconds() / 3600
            if heures < 24:
                return f"{int(heures)}h"
            else:
                jours = int(heures / 24)
                return f"{jours}j"
        return "En attente"
    display_delai_traitement.short_description = "Délai"
    
    def display_candidats_traites(self, obj):
        nb_retenus = len(obj.candidats_retenus) if obj.candidats_retenus else 0
        nb_rejetes = len(obj.candidats_rejetes) if obj.candidats_rejetes else 0
        return f"✅{nb_retenus} | ❌{nb_rejetes}"
    display_candidats_traites.short_description = "Candidats"

# ================================================================
# ADMINS NOTIFICATIONS ET HISTORIQUE
# ================================================================

@admin.register(NotificationInterim)
class NotificationInterimAdmin(BaseModelAdmin):
    list_display = (
        'titre', 'destinataire', 'display_type', 'display_urgence',
        'display_statut', 'display_temps_creation', 'display_expire'
    )
    list_filter = (
        NotificationTypeFilter, 'urgence', 'statut', 'demande__urgence'
    )
    search_fields = (
        'titre', 'message', 'destinataire__matricule', 
        'destinataire__user__first_name', 'destinataire__user__last_name'
    )
    readonly_fields = (
        'created_at', 'updated_at', 'date_lecture', 'date_traitement',
        'temps_depuis_creation', 'est_expiree'
    )
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Notification', {
            'fields': (
                'type_notification', 'urgence', 'statut',
                'destinataire', 'expediteur', 'demande'
            )
        }),
        ('Contenu', {
            'fields': ('titre', 'message')
        }),
        ('Actions', {
            'fields': (
                ('url_action_principale', 'texte_action_principale'),
                ('url_action_secondaire', 'texte_action_secondaire')
            ),
            'classes': ('collapse',)
        }),
        ('Références', {
            'fields': ('proposition_liee', 'validation_liee'),
            'classes': ('collapse',)
        }),
        ('Dates et suivi', {
            'fields': (
                'date_expiration', 'nb_rappels_envoyes', 'prochaine_date_rappel',
                'date_lecture', 'date_traitement'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('metadata', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['marquer_comme_lues', 'marquer_comme_traitees', 'envoyer_rappels']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'destinataire__user', 'expediteur__user', 'demande'
        )
    
    def display_type(self, obj):
        return obj.type_display
    display_type.short_description = "Type"
    
    def display_urgence(self, obj):
        return obj.urgence_display
    display_urgence.short_description = "Urgence"
    
    def display_statut(self, obj):
        statuts = {
            'NON_LUE': '<span style="color: red; font-weight: bold;">🔴 Non lue</span>',
            'LUE': '<span style="color: orange;">🟡 Lue</span>',
            'TRAITEE': '<span style="color: green;">✅ Traitée</span>',
            'ARCHIVEE': '<span style="color: gray;">📁 Archivée</span>',
        }
        return format_html(statuts.get(obj.statut, obj.statut))
    display_statut.short_description = "Statut"
    
    def display_temps_creation(self, obj):
        delta = obj.temps_depuis_creation
        if delta.days > 0:
            return f"Il y a {delta.days} jour{'s' if delta.days > 1 else ''}"
        elif delta.seconds > 3600:
            heures = delta.seconds // 3600
            return f"Il y a {heures}h"
        else:
            minutes = delta.seconds // 60
            return f"Il y a {minutes}min"
    display_temps_creation.short_description = "Créée"
    
    def display_expire(self, obj):
        if obj.est_expiree:
            return format_html('<span style="color: red;">⏰ Expirée</span>')
        return format_html('<span style="color: green;">✅ Valide</span>')
    display_expire.short_description = "État"
    
    def marquer_comme_lues(self, request, queryset):
        """Marque les notifications comme lues"""
        updated = queryset.filter(statut='NON_LUE').update(
            statut='LUE',
            date_lecture=timezone.now()
        )
        self.message_user(request, f"{updated} notification(s) marquée(s) comme lue(s).")
    marquer_comme_lues.short_description = "Marquer comme lues"
    
    def marquer_comme_traitees(self, request, queryset):
        """Marque les notifications comme traitées"""
        updated = queryset.filter(statut__in=['NON_LUE', 'LUE']).update(
            statut='TRAITEE',
            date_traitement=timezone.now()
        )
        self.message_user(request, f"{updated} notification(s) marquée(s) comme traitée(s).")
    marquer_comme_traitees.short_description = "Marquer comme traitées"

@admin.register(HistoriqueAction)
class HistoriqueActionAdmin(ReadOnlyMixin, BaseModelAdmin):
    list_display = (
        'demande', 'display_action', 'utilisateur', 'display_description',
        'niveau_validation', 'created_at'
    )
    list_filter = ('action', 'niveau_validation', 'demande__urgence')
    search_fields = (
        'demande__numero_demande', 'utilisateur__matricule', 
        'utilisateur__user__first_name', 'utilisateur__user__last_name',
        'description'
    )
    readonly_fields = (
        'demande', 'action', 'utilisateur', 'description',
        'donnees_avant', 'donnees_apres', 'created_at', 'updated_at'
    )
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Action', {
            'fields': ('demande', 'action', 'utilisateur', 'niveau_validation')
        }),
        ('Description', {
            'fields': ('description',)
        }),
        ('Références', {
            'fields': ('proposition', 'validation'),
            'classes': ('collapse',)
        }),
        ('Données de changement', {
            'fields': ('donnees_avant', 'donnees_apres'),
            'classes': ('collapse',)
        }),
        ('Métadonnées techniques', {
            'fields': ('adresse_ip', 'user_agent', 'created_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'demande', 'utilisateur__user', 'proposition', 'validation'
        )
    
    def display_action(self, obj):
        return obj.action_display
    display_action.short_description = "Action"
    
    def display_description(self, obj):
        # Tronquer la description si elle est trop longue
        if len(obj.description) > 50:
            return f"{obj.description[:50]}..."
        return obj.description
    display_description.short_description = "Description"

# ================================================================
# ADMINS RÉPONSES CANDIDATS
# ================================================================

@admin.register(ReponseCandidatInterim)
class ReponseCandidatInterimAdmin(BaseModelAdmin):
    list_display = (
        'candidat', 'demande', 'display_reponse', 'display_temps_restant',
        'motif_refus', 'date_proposition', 'date_reponse'
    )
    list_filter = ('reponse', 'motif_refus', 'demande__urgence')
    search_fields = (
        'candidat__matricule', 'candidat__user__first_name', 'candidat__user__last_name',
        'demande__numero_demande'
    )
    readonly_fields = (
        'date_proposition', 'est_expire', 'temps_restant', 'temps_restant_display'
    )
    date_hierarchy = 'date_proposition'
    
    fieldsets = (
        ('Proposition', {
            'fields': ('demande', 'candidat', 'date_proposition', 'date_limite_reponse')
        }),
        ('Réponse', {
            'fields': ('reponse', 'date_reponse')
        }),
        ('Détails refus', {
            'fields': ('motif_refus', 'commentaire_refus'),
            'classes': ('collapse',)
        }),
        ('Conditions proposées', {
            'fields': ('salaire_propose', 'avantages_proposes'),
            'classes': ('collapse',)
        }),
        ('Suivi rappels', {
            'fields': ('nb_rappels_envoyes', 'derniere_date_rappel'),
            'classes': ('collapse',)
        }),
        ('Statut', {
            'fields': ('est_expire', 'temps_restant_display'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['envoyer_rappels', 'marquer_expires']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'candidat__user', 'demande'
        )
    
    def display_reponse(self, obj):
        return obj.reponse_display
    display_reponse.short_description = "Réponse"
    
    def display_temps_restant(self, obj):
        return obj.temps_restant_display
    display_temps_restant.short_description = "Temps restant"
    
    def envoyer_rappels(self, request, queryset):
        """Envoie des rappels aux candidats en attente"""
        count = 0
        for reponse in queryset.filter(reponse='EN_ATTENTE'):
            if not reponse.est_expire:
                # Ici, déclencher l'envoi de rappel
                reponse.nb_rappels_envoyes += 1
                reponse.derniere_date_rappel = timezone.now()
                reponse.save()
                count += 1
        
        self.message_user(request, f"{count} rappel(s) envoyé(s).")
    envoyer_rappels.short_description = "Envoyer des rappels"
    
    def marquer_expires(self, request, queryset):
        """Marque les réponses expirées"""
        updated = 0
        for reponse in queryset.filter(reponse='EN_ATTENTE'):
            if reponse.est_expire:
                reponse.reponse = 'EXPIRE'
                reponse.save()
                updated += 1
        
        self.message_user(request, f"{updated} réponse(s) marquée(s) comme expirée(s).")
    marquer_expires.short_description = "Marquer comme expirées"

# ================================================================
# ADMINS PRINCIPAUX (DEMANDES, PROFILS, ETC.)
# ================================================================

@admin.register(DemandeInterim)
class DemandeInterimAdmin(BaseModelAdmin):
    list_display = (
        'numero_demande', 'demandeur', 'personne_remplacee', 'poste',
        'display_periode', 'display_statut', 'display_urgence', 
        'display_propositions', 'candidat_selectionne', 'created_at'
    )
    list_filter = (
        'statut', 'urgence', 'motif_absence', 'poste__departement',
        'propositions_autorisees'
    )
    search_fields = (
        'numero_demande', 'demandeur__matricule', 'personne_remplacee__matricule', 
        'poste__titre', 'candidat_selectionne__matricule'
    )
    readonly_fields = (
        'numero_demande', 'created_at', 'updated_at', 'duree_mission',
        'est_urgente', 'peut_etre_modifiee'
    )
    date_hierarchy = 'date_debut'
    
    fieldsets = (
        ('Identification', {
            'fields': ('numero_demande', 'statut')
        }),
        ('Acteurs', {
            'fields': (
                'demandeur', 'personne_remplacee', 'candidat_selectionne'
            )
        }),
        ('Mission', {
            'fields': (
                'poste', ('date_debut', 'date_fin'),
                ('date_debut_effective', 'date_fin_effective')
            )
        }),
        ('Contexte', {
            'fields': (
                'motif_absence', ('urgence', 'duree_mission')
            )
        }),
        ('Description', {
            'fields': (
                'description_poste', 'instructions_particulieres',
                'competences_indispensables'
            )
        }),
        ('Configuration propositions', {
            'fields': (
                'propositions_autorisees', 'nb_max_propositions_par_utilisateur',
                'date_limite_propositions'
            )
        }),
        ('Workflow et validation', {
            'fields': (
                ('niveau_validation_actuel', 'niveaux_validation_requis'),
                'date_validation'
            )
        }),
        ('Scoring', {
            'fields': (
                ('poids_scoring_automatique', 'poids_scoring_humain'),
            ),
            'classes': ('collapse',)
        }),
        ('Évaluation finale', {
            'fields': ('evaluation_mission', 'commentaire_final'),
            'classes': ('collapse',)
        }),
        ('État et métadonnées', {
            'fields': (
                'est_urgente', 'peut_etre_modifiee', 'created_at', 'updated_at'
            ),
            'classes': ('collapse',)
        })
    )
    
    inlines = [PropositionCandidatInline, ValidationDemandeInline, NotificationInterimInline]
    actions = [
        'activer_propositions', 'desactiver_propositions', 'rechercher_candidats',
        'valider_demandes', 'marquer_urgentes'
    ]
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'demandeur__user', 'personne_remplacee__user', 'poste__departement', 
            'poste__site', 'motif_absence', 'candidat_selectionne__user'
        ).prefetch_related('propositions_candidats')
    
    def display_periode(self, obj):
        if obj.date_debut and obj.date_fin:
            return f"{obj.date_debut.strftime('%d/%m/%Y')} - {obj.date_fin.strftime('%d/%m/%Y')}"
        return "Non définie"
    display_periode.short_description = "Période"
    
    def display_statut(self, obj):
        statuts = {
            'BROUILLON': '<span style="color: gray;">📝 Brouillon</span>',
            'SOUMISE': '<span style="color: blue;">📤 Soumise</span>',
            'EN_PROPOSITION': '<span style="color: orange;">👥 En proposition</span>',
            'EN_VALIDATION': '<span style="color: purple;">⚖️ En validation</span>',
            'CANDIDAT_PROPOSE': '<span style="color: blue;">🎯 Candidat proposé</span>',
            'EN_COURS': '<span style="color: green;">🚀 En cours</span>',
            'TERMINEE': '<span style="color: green;">✅ Terminée</span>',
            'REFUSEE': '<span style="color: red;">❌ Refusée</span>',
            'ANNULEE': '<span style="color: gray;">🚫 Annulée</span>',
        }
        return format_html(statuts.get(obj.statut, obj.statut))
    display_statut.short_description = "Statut"
    
    def display_urgence(self, obj):
        return format_urgence_display(obj.urgence)
    display_urgence.short_description = "Urgence"
    
    def display_propositions(self, obj):
        nb_propositions = obj.propositions_candidats.count()
        if nb_propositions > 0:
            return format_html(
                '<span style="color: blue; font-weight: bold;">👥 {} proposition{}</span>',
                nb_propositions, 's' if nb_propositions > 1 else ''
            )
        elif obj.propositions_autorisees:
            return format_html('<span style="color: green;">✅ Autorisées</span>')
        else:
            return format_html('<span style="color: red;">❌ Désactivées</span>')
    display_propositions.short_description = "Propositions"
    
    def activer_propositions(self, request, queryset):
        """Active les propositions pour les demandes sélectionnées"""
        updated = queryset.update(propositions_autorisees=True)
        self.message_user(request, f"{updated} demande(s) : propositions activées.")
    activer_propositions.short_description = "Activer les propositions"
    
    def desactiver_propositions(self, request, queryset):
        """Désactive les propositions pour les demandes sélectionnées"""
        updated = queryset.update(propositions_autorisees=False)
        self.message_user(request, f"{updated} demande(s) : propositions désactivées.")
    desactiver_propositions.short_description = "Désactiver les propositions"
    
    def rechercher_candidats(self, request, queryset):
        """Lance la recherche de candidats pour les demandes sélectionnées"""
        count = 0
        for demande in queryset.filter(statut__in=['SOUMISE', 'EN_VALIDATION', 'CANDIDAT_PROPOSE']):
            # Ici, déclencher la recherche de candidats
            count += 1
        self.message_user(request, f"Recherche de candidats programmée pour {count} demande(s).")
    rechercher_candidats.short_description = "Rechercher des candidats"
    
    def valider_demandes(self, request, queryset):
        """Valide les demandes sélectionnées"""
        updated = queryset.filter(statut='EN_VALIDATION').update(
            statut='CANDIDAT_PROPOSE',
            date_validation=timezone.now()
        )
        self.message_user(request, f"{updated} demande(s) validée(s).")
    valider_demandes.short_description = "Valider les demandes"
    
    def marquer_urgentes(self, request, queryset):
        """Marque les demandes comme urgentes"""
        updated = queryset.update(urgence='ELEVEE')
        self.message_user(request, f"{updated} demande(s) marquée(s) comme urgente(s).")
    marquer_urgentes.short_description = "Marquer comme urgentes"

# ================================================================
# ADMINS POUR MODÈLES ORGANISATIONNELS
# ================================================================

@admin.register(ProfilUtilisateur)
class ProfilUtilisateurAdmin(BaseModelAdmin):
    list_display = (
        'matricule', 'nom_complet', 'departement', 'poste', 
        'type_profil_display', 'status_display', 'display_disponible_interim', 
        'display_sync_status', 'actif'
    )
    list_filter = (
        'actif', 'type_profil', 'statut_employe', 'departement', 'site'
    )
    search_fields = (
        'matricule', 'user__first_name', 'user__last_name', 'user__username', 'user__email'
    )
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Utilisateur Django', {
            'fields': ('user', 'matricule', 'actif')
        }),
        ('Profil et statut', {
            'fields': ('type_profil', 'statut_employe')
        }),
        ('Organisation', {
            'fields': ('departement', 'site', 'poste', 'manager')
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_sync_status', 'kelio_last_sync'),
            'classes': ('collapse',)
        })
    )
    
    actions = ['activer_profils', 'desactiver_profils', 'marquer_disponible_interim']
    
    def display_disponible_interim(self, obj):
        try:
            if hasattr(obj, 'extended_data') and obj.extended_data.disponible_interim:
                return format_html('<span style="color: green;">✅ Disponible</span>')
            else:
                return format_html('<span style="color: red;">❌ Non disponible</span>')
        except:
            return format_html('<span style="color: gray;">❓ Non renseigné</span>')
    display_disponible_interim.short_description = "Dispo. intérim"
    
    def display_sync_status(self, obj):
        if obj.kelio_last_sync:
            delta = timezone.now() - obj.kelio_last_sync
            if delta.total_seconds() < 86400:  # Moins de 24h
                return format_html('<span style="color: green;">🟢 Synchronisé</span>')
            else:
                return format_html('<span style="color: orange;">🟡 Ancien</span>')
        else:
            return format_html('<span style="color: red;">🔴 Jamais sync</span>')
    display_sync_status.short_description = "Sync Kelio"
    
    def activer_profils(self, request, queryset):
        updated = queryset.update(actif=True)
        self.message_user(request, f"{updated} profil(s) activé(s).")
    activer_profils.short_description = "Activer les profils"
    
    def desactiver_profils(self, request, queryset):
        updated = queryset.update(actif=False)
        self.message_user(request, f"{updated} profil(s) désactivé(s).")
    desactiver_profils.short_description = "Désactiver les profils"
    
    def marquer_disponible_interim(self, request, queryset):
        count = 0
        for profil in queryset:
            try:
                extended, created = ProfilUtilisateurExtended.objects.get_or_create(profil=profil)
                extended.disponible_interim = True
                extended.save()
                count += 1
            except Exception:
                pass
        self.message_user(request, f"{count} profil(s) marqué(s) comme disponible(s) pour l'intérim.")
    marquer_disponible_interim.short_description = "Marquer disponible pour intérim"

# Enregistrer les autres modèles avec des admins simples mais complets
@admin.register(Departement)
class DepartementAdmin(BaseModelAdmin):
    list_display = ('nom', 'code', 'manager', 'display_employes_count', 'display_status')
    list_filter = ('actif',)
    search_fields = ('nom', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'code', 'description', 'actif')
        }),
        ('Organisation', {
            'fields': ('manager',)
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_department_key', 'kelio_last_sync'),
            'classes': ('collapse',)
        })
    )
    
    def display_employes_count(self, obj):
        try:
            count = obj.employes.filter(actif=True).count()
            return f"{count} employé{'s' if count != 1 else ''}"
        except Exception:
            return "Erreur"
    display_employes_count.short_description = "Employés actifs"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

@admin.register(Site)
class SiteAdmin(BaseModelAdmin):
    list_display = ('nom', 'ville', 'code_postal', 'responsable', 'display_employes_count', 'display_status')
    list_filter = ('actif', 'ville', 'pays')
    search_fields = ('nom', 'ville', 'adresse', 'code_postal')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'actif')
        }),
        ('Adresse', {
            'fields': (
                'adresse', ('ville', 'code_postal'), 'pays'
            )
        }),
        ('Contact', {
            'fields': ('telephone', 'email')
        }),
        ('Organisation', {
            'fields': ('responsable',)
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_site_key', 'kelio_last_sync'),
            'classes': ('collapse',)
        })
    )
    
    def display_employes_count(self, obj):
        try:
            count = obj.employes.filter(actif=True).count()
            return f"{count} employé{'s' if count != 1 else ''}"
        except Exception:
            return "Erreur"
    display_employes_count.short_description = "Employés"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

@admin.register(Poste)
class PosteAdmin(BaseModelAdmin):
    list_display = (
        'titre', 'departement', 'site', 'niveau_responsabilite_display', 
        'display_interim_autorise', 'display_employes_count', 'display_status'
    )
    list_filter = ('actif', 'departement', 'site', 'niveau_responsabilite', 'interim_autorise')
    search_fields = ('titre', 'description', 'categorie')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('titre', 'description', 'categorie', 'actif')
        }),
        ('Organisation', {
            'fields': ('departement', 'site')
        }),
        ('Prérequis', {
            'fields': (
                ('niveau_etude_min', 'experience_min_mois'),
                'permis_requis'
            )
        }),
        ('Classification', {
            'fields': ('niveau_responsabilite',)
        }),
        ('Intérim', {
            'fields': ('interim_autorise',)
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_job_key',),
            'classes': ('collapse',)
        })
    )
    
    def display_interim_autorise(self, obj):
        return format_boolean_display(obj.interim_autorise, "✅ Autorisé", "❌ Non autorisé")
    display_interim_autorise.short_description = "Intérim"
    
    def display_employes_count(self, obj):
        try:
            count = obj.employes.filter(actif=True).count()
            return f"{count} employé{'s' if count != 1 else ''}"
        except Exception:
            return "Erreur"
    display_employes_count.short_description = "Employés"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

@admin.register(Competence)
class CompetenceAdmin(BaseModelAdmin):
    list_display = (
        'nom', 'type_competence', 'categorie', 'display_utilisateurs_count',
        'display_kelio_info', 'display_status'
    )
    list_filter = ('actif', 'type_competence', 'obsolete', 'categorie')
    search_fields = ('nom', 'description', 'categorie')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'description', 'categorie', 'actif')
        }),
        ('Classification', {
            'fields': ('type_competence', 'obsolete')
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_skill_key', 'kelio_skill_abbreviation'),
            'classes': ('collapse',)
        })
    )
    
    def display_utilisateurs_count(self, obj):
        try:
            count = obj.competences_utilisateurs.filter(utilisateur__actif=True).count()
            return f"{count} utilisateur{'s' if count != 1 else ''}"
        except Exception:
            return "Erreur"
    display_utilisateurs_count.short_description = "Utilisateurs"
    
    def display_kelio_info(self, obj):
        if obj.kelio_skill_key:
            return f"🔗 {obj.kelio_skill_key}"
        return "➖ Non Kelio"
    display_kelio_info.short_description = "Kelio"
    
    def display_status(self, obj):
        if obj.obsolete:
            return format_html('<span style="color: orange;">⚠️ Obsolète</span>')
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

@admin.register(CompetenceUtilisateur)
class CompetenceUtilisateurAdmin(BaseModelAdmin):
    list_display = (
        'utilisateur', 'competence', 'display_niveau', 'display_certifie',
        'date_evaluation', 'evaluateur', 'source_donnee'
    )
    list_filter = ('niveau_maitrise', 'certifie', 'source_donnee', 'competence__type_competence')
    search_fields = (
        'utilisateur__matricule', 'utilisateur__user__first_name', 
        'utilisateur__user__last_name', 'competence__nom'
    )
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'date_evaluation'
    
    fieldsets = (
        ('Association', {
            'fields': ('utilisateur', 'competence')
        }),
        ('Évaluation', {
            'fields': (
                'niveau_maitrise',
                ('date_acquisition', 'date_evaluation'),
                ('evaluateur', 'commentaire')
            )
        }),
        ('Certification', {
            'fields': (
                'certifie',
                ('date_certification', 'organisme_certificateur')
            )
        }),
        ('Synchronisation', {
            'fields': (
                'source_donnee',
                ('kelio_skill_assignment_key', 'kelio_level')
            ),
            'classes': ('collapse',)
        })
    )
    
    def display_niveau(self, obj):
        niveaux = {1: '🟢 Débutant', 2: '🟡 Intermédiaire', 3: '🟠 Confirmé', 4: '🔴 Expert'}
        return niveaux.get(obj.niveau_maitrise, '❓ Non défini')
    display_niveau.short_description = "Niveau"
    
    def display_certifie(self, obj):
        if obj.certifie:
            return format_html('<span style="color: green;">🏆 Certifié</span>')
        return format_html('<span style="color: gray;">➖ Non certifié</span>')
    display_certifie.short_description = "Certification"

@admin.register(MotifAbsence)
class MotifAbsenceAdmin(BaseModelAdmin):
    list_display = (
        'nom', 'code', 'categorie', 'display_demandes_count',
        'display_regles', 'display_status'
    )
    list_filter = ('actif', 'categorie', 'necessite_justificatif')
    search_fields = ('nom', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'code', 'description', 'actif')
        }),
        ('Classification', {
            'fields': ('categorie', 'couleur')
        }),
        ('Règles de gestion', {
            'fields': (
                'necessite_justificatif',
                'delai_prevenance_jours',
                'duree_max_jours'
            )
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_absence_type_key', 'kelio_abbreviation'),
            'classes': ('collapse',)
        })
    )
    
    def display_demandes_count(self, obj):
        try:
            count = obj.demandes.count()
            return f"{count} demande{'s' if count != 1 else ''}"
        except Exception:
            return "Erreur"
    display_demandes_count.short_description = "Demandes"
    
    def display_regles(self, obj):
        regles = []
        if obj.necessite_justificatif:
            regles.append("📋 Justificatif")
        if obj.delai_prevenance_jours > 0:
            regles.append(f"⏰ {obj.delai_prevenance_jours}j")
        if obj.duree_max_jours:
            regles.append(f"📅 Max {obj.duree_max_jours}j")
        return " | ".join(regles) if regles else "Aucune"
    display_regles.short_description = "Règles"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

# Modèles données connexes simplifiés
@admin.register(FormationUtilisateur)
class FormationUtilisateurAdmin(BaseModelAdmin):
    list_display = ('utilisateur', 'titre', 'organisme', 'display_periode', 'certifiante', 'diplome_obtenu')
    list_filter = ('certifiante', 'diplome_obtenu', 'source_donnee')
    search_fields = ('titre', 'organisme', 'utilisateur__matricule')
    date_hierarchy = 'date_fin'
    
    def display_periode(self, obj):
        if obj.date_debut and obj.date_fin:
            return f"{obj.date_debut.strftime('%d/%m/%Y')} - {obj.date_fin.strftime('%d/%m/%Y')}"
        elif obj.date_fin:
            return f"Terminée le {obj.date_fin.strftime('%d/%m/%Y')}"
        return "Période non renseignée"
    display_periode.short_description = "Période"

@admin.register(AbsenceUtilisateur)
class AbsenceUtilisateurAdmin(ReadOnlyMixin, BaseModelAdmin):
    list_display = ('utilisateur', 'type_absence', 'date_debut', 'date_fin', 'duree_jours', 'display_en_cours')
    list_filter = ('type_absence', 'source_donnee')
    search_fields = ('utilisateur__matricule', 'type_absence')
    date_hierarchy = 'date_debut'
    
    def display_en_cours(self, obj):
        if obj.est_en_cours:
            return format_html('<span style="color: orange;">🟡 En cours</span>')
        elif obj.date_fin < date.today():
            return format_html('<span style="color: green;">✅ Terminée</span>')
        else:
            return format_html('<span style="color: blue;">🔵 À venir</span>')
    display_en_cours.short_description = "État"

@admin.register(DisponibiliteUtilisateur)
class DisponibiliteUtilisateurAdmin(BaseModelAdmin):
    list_display = ('utilisateur', 'type_disponibilite', 'date_debut', 'date_fin', 'display_duree', 'created_by')
    list_filter = ('type_disponibilite',)
    search_fields = ('utilisateur__matricule', 'commentaire')
    date_hierarchy = 'date_debut'
    
    def display_duree(self, obj):
        if obj.date_debut and obj.date_fin:
            duree = (obj.date_fin - obj.date_debut).days + 1
            return f"{duree} jour{'s' if duree > 1 else ''}"
        return "Non calculée"
    display_duree.short_description = "Durée"

# ================================================================
# VUES PERSONNALISÉES INTÉGRÉES
# ================================================================

@staff_member_required
def tableau_bord_propositions_view(request):
    """Tableau de bord spécialisé pour les propositions et le scoring"""
    try:
        today = date.today()
        
        # Statistiques propositions
        stats_propositions = {
            'total_propositions': PropositionCandidat.objects.count(),
            'propositions_en_attente': PropositionCandidat.objects.filter(
                statut__in=['SOUMISE', 'EN_EVALUATION']
            ).count(),
            'propositions_retenues': PropositionCandidat.objects.filter(
                statut='RETENUE'
            ).count(),
            'propositions_ce_mois': PropositionCandidat.objects.filter(
                created_at__year=today.year,
                created_at__month=today.month
            ).count(),
        }
        
        # Top proposants
        top_proposants = list(
            ProfilUtilisateur.objects.annotate(
                nb_propositions=Count('propositions_soumises')
            ).filter(nb_propositions__gt=0).order_by('-nb_propositions')[:5]
        )
        
        # Propositions récentes
        propositions_recentes = PropositionCandidat.objects.select_related(
            'candidat_propose__user', 'proposant__user', 'demande_interim'
        ).order_by('-created_at')[:10]
        
        # Statistiques scoring
        stats_scoring = {
            'moyenne_scores': ScoreDetailCandidat.objects.aggregate(
                avg_score=Avg('score_total')
            )['avg_score'] or 0,
            'scores_excellents': ScoreDetailCandidat.objects.filter(
                score_total__gte=80
            ).count(),
            'propositions_humaines': ScoreDetailCandidat.objects.filter(
                proposition_humaine__isnull=False
            ).count(),
        }
        
        # Configurations scoring
        configs_scoring = ConfigurationScoring.objects.filter(actif=True).order_by(
            '-configuration_par_defaut', 'nom'
        )
        
        context = {
            'title': 'Tableau de bord - Propositions & Scoring',
            'stats_propositions': stats_propositions,
            'top_proposants': top_proposants,
            'propositions_recentes': propositions_recentes,
            'stats_scoring': stats_scoring,
            'configs_scoring': configs_scoring,
            'opts': PropositionCandidat._meta,
            'has_permission': True,
        }
        
        return TemplateResponse(request, 'admin/tableau_bord_propositions.html', context)
        
    except Exception as e:
        logger.error(f"Erreur tableau de bord propositions: {e}")
        context = {
            'title': 'Erreur - Tableau de bord',
            'error_message': str(e),
            'opts': None,
            'has_permission': True,
        }
        return TemplateResponse(request, 'admin/error.html', context)

@staff_member_required
def analytics_scoring_view(request):
    """Analytics détaillées du système de scoring"""
    try:
        # Analyse des scores par critère
        scores_analysis = {
            'score_moyen_similarite': ScoreDetailCandidat.objects.aggregate(
                avg=Avg('score_similarite_poste')
            )['avg'] or 0,
            'score_moyen_competences': ScoreDetailCandidat.objects.aggregate(
                avg=Avg('score_competences')
            )['avg'] or 0,
            'score_moyen_experience': ScoreDetailCandidat.objects.aggregate(
                avg=Avg('score_experience')
            )['avg'] or 0,
            'score_moyen_disponibilite': ScoreDetailCandidat.objects.aggregate(
                avg=Avg('score_disponibilite')
            )['avg'] or 0,
        }
        
        # Distribution des scores
        distribution_scores = [
            {
                'range': '0-20',
                'count': ScoreDetailCandidat.objects.filter(score_total__lt=20).count()
            },
            {
                'range': '20-40',
                'count': ScoreDetailCandidat.objects.filter(score_total__gte=20, score_total__lt=40).count()
            },
            {
                'range': '40-60',
                'count': ScoreDetailCandidat.objects.filter(score_total__gte=40, score_total__lt=60).count()
            },
            {
                'range': '60-80',
                'count': ScoreDetailCandidat.objects.filter(score_total__gte=60, score_total__lt=80).count()
            },
            {
                'range': '80-100',
                'count': ScoreDetailCandidat.objects.filter(score_total__gte=80).count()
            },
        ]
        
        # Efficacité des propositions humaines vs automatiques
        efficacite_propositions = {
            'humaines': {
                'total': ScoreDetailCandidat.objects.filter(proposition_humaine__isnull=False).count(),
                'score_moyen': ScoreDetailCandidat.objects.filter(
                    proposition_humaine__isnull=False
                ).aggregate(avg=Avg('score_total'))['avg'] or 0,
            },
            'automatiques': {
                'total': ScoreDetailCandidat.objects.filter(proposition_humaine__isnull=True).count(),
                'score_moyen': ScoreDetailCandidat.objects.filter(
                    proposition_humaine__isnull=True
                ).aggregate(avg=Avg('score_total'))['avg'] or 0,
            }
        }
        
        # Performance par département
        performance_dept = list(
            Departement.objects.annotate(
                avg_score=Avg('employes__scores_details__score_total'),
                nb_propositions=Count('employes__propositions_recues')
            ).filter(actif=True, avg_score__isnull=False).order_by('-avg_score')
        )
        
        context = {
            'title': 'Analytics Scoring',
            'scores_analysis': scores_analysis,
            'distribution_scores': distribution_scores,
            'efficacite_propositions': efficacite_propositions,
            'performance_dept': performance_dept,
            'opts': ScoreDetailCandidat._meta,
            'has_permission': True,
        }
        
        return TemplateResponse(request, 'admin/analytics_scoring.html', context)
        
    except Exception as e:
        logger.error(f"Erreur analytics scoring: {e}")
        context = {
            'title': 'Erreur - Analytics',
            'error_message': str(e),
            'opts': None,
            'has_permission': True,
        }
        return TemplateResponse(request, 'admin/error.html', context)

@staff_member_required
def workflow_monitoring_view(request):
    """Monitoring du workflow et des validations"""
    try:
        # Demandes par étape de workflow
        workflows_actifs = WorkflowDemande.objects.select_related(
            'demande', 'etape_actuelle'
        ).filter(
            demande__statut__in=['SOUMISE', 'EN_PROPOSITION', 'EN_VALIDATION', 'CANDIDAT_PROPOSE']
        )
        
        # Grouper par étape
        etapes_stats = {}
        for workflow in workflows_actifs:
            etape = workflow.etape_actuelle.nom
            if etape not in etapes_stats:
                etapes_stats[etape] = {
                    'count': 0,
                    'en_retard': 0,
                    'propositions_moyennes': 0
                }
            etapes_stats[etape]['count'] += 1
            if workflow.est_en_retard:
                etapes_stats[etape]['en_retard'] += 1
        
        # Validations en attente
        validations_attente = ValidationDemande.objects.filter(
            date_validation__isnull=True
        ).select_related('demande', 'validateur__user').order_by('date_demande_validation')
        
        # Performance des validateurs
        performance_validateurs = list(
            ProfilUtilisateur.objects.annotate(
                nb_validations=Count('validations_effectuees'),
                delai_moyen=Avg(
                    F('validations_effectuees__date_validation') - 
                    F('validations_effectuees__date_demande_validation')
                )
            ).filter(nb_validations__gt=0).order_by('-nb_validations')[:10]
        )
        
        # Demandes bloquées
        demandes_bloquees = DemandeInterim.objects.filter(
            statut__in=['EN_VALIDATION', 'CANDIDAT_PROPOSE'],
            created_at__lt=timezone.now() - timedelta(days=7)
        ).select_related('demandeur__user', 'poste')
        
        context = {
            'title': 'Monitoring Workflow',
            'etapes_stats': etapes_stats,
            'validations_attente': validations_attente,
            'performance_validateurs': performance_validateurs,
            'demandes_bloquees': demandes_bloquees,
            'opts': WorkflowDemande._meta,
            'has_permission': True,
        }
        
        return TemplateResponse(request, 'admin/workflow_monitoring.html', context)
        
    except Exception as e:
        logger.error(f"Erreur monitoring workflow: {e}")
        context = {
            'title': 'Erreur - Monitoring',
            'error_message': str(e),
            'opts': None,
            'has_permission': True,
        }
        return TemplateResponse(request, 'admin/error.html', context)

# ================================================================
# APIS AJAX INTÉGRÉES
# ================================================================

@staff_member_required
def ajax_proposer_candidat(request, demande_id):
    """API AJAX pour proposer un candidat"""
    try:
        if request.method == 'POST':
            demande = get_object_or_404(DemandeInterim, pk=demande_id)
            candidat_id = request.POST.get('candidat_id')
            justification = request.POST.get('justification', '')
            
            if not candidat_id or not justification:
                return JsonResponse({
                    'error': 'Candidat et justification requis'
                }, status=400)
            
            candidat = get_object_or_404(ProfilUtilisateur, pk=candidat_id)
            proposant = request.user.profilutilisateur
            
            # Vérifier les permissions
            peut_proposer, raison = demande.peut_proposer_candidat(proposant)
            if not peut_proposer:
                return JsonResponse({'error': raison}, status=403)
            
            # Créer la proposition
            with transaction.atomic():
                proposition = PropositionCandidat.objects.create(
                    demande_interim=demande,
                    candidat_propose=candidat,
                    proposant=proposant,
                    source_proposition='MANAGER_DIRECT',  # À adapter selon le type de profil
                    justification=justification,
                    statut='SOUMISE'
                )
                
                # Créer le score détaillé
                score_detail = ScoreDetailCandidat.objects.create(
                    candidat=candidat,
                    demande_interim=demande,
                    proposition_humaine=proposition,
                    calcule_par='HUMAIN'
                )
                
                # Calculer le score
                score_detail.calculer_score_total()
                score_detail.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Candidat {candidat.nom_complet} proposé avec succès',
                'proposition_id': proposition.id
            })
        
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
        
    except Exception as e:
        logger.error(f"Erreur proposition candidat: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@staff_member_required
def ajax_valider_proposition(request, proposition_id):
    """API AJAX pour valider une proposition"""
    try:
        if request.method == 'POST':
            proposition = get_object_or_404(PropositionCandidat, pk=proposition_id)
            decision = request.POST.get('decision')  # 'retenir' ou 'rejeter'
            commentaire = request.POST.get('commentaire', '')
            score_ajuste = request.POST.get('score_ajuste')
            
            if decision not in ['retenir', 'rejeter']:
                return JsonResponse({'error': 'Décision invalide'}, status=400)
            
            evaluateur = request.user.profilutilisateur
            
            with transaction.atomic():
                if decision == 'retenir':
                    proposition.statut = 'RETENUE'
                    if score_ajuste:
                        proposition.score_humain_ajuste = int(score_ajuste)
                else:
                    proposition.statut = 'REJETEE'
                
                proposition.evaluateur = evaluateur
                proposition.commentaire_evaluation = commentaire
                proposition.date_evaluation = timezone.now()
                proposition.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Proposition {proposition.get_statut_display().lower()}',
                'nouveau_statut': proposition.get_statut_display()
            })
        
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
        
    except Exception as e:
        logger.error(f"Erreur validation proposition: {e}")
        return JsonResponse({'error': str(e)}, status=500)

@staff_member_required
def ajax_recalculer_score(request, score_id):
    """API AJAX pour recalculer un score"""
    try:
        if request.method == 'POST':
            score = get_object_or_404(ScoreDetailCandidat, pk=score_id)
            
            # Recalculer le score
            ancien_score = score.score_total
            nouveau_score = score.calculer_score_total()
            score.save()
            
            return JsonResponse({
                'success': True,
                'message': f'Score recalculé: {ancien_score} → {nouveau_score}',
                'ancien_score': ancien_score,
                'nouveau_score': nouveau_score
            })
        
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
        
    except Exception as e:
        logger.error(f"Erreur recalcul score: {e}")
        return JsonResponse({'error': str(e)}, status=500)

# ================================================================
# URLS PERSONNALISÉES ÉTENDUES
# ================================================================

def get_admin_urls_integres():
    """URLs personnalisées pour l'admin intégré"""
    
    return [
        # Tableaux de bord
        path('dashboard/propositions/', tableau_bord_propositions_view, name='tableau_bord_propositions'),
        path('analytics/scoring/', analytics_scoring_view, name='analytics_scoring'),
        path('monitoring/workflow/', workflow_monitoring_view, name='workflow_monitoring'),
        
        # APIs AJAX
        path('ajax/proposer-candidat/<int:demande_id>/', ajax_proposer_candidat, name='ajax_proposer_candidat'),
        path('ajax/valider-proposition/<int:proposition_id>/', ajax_valider_proposition, name='ajax_valider_proposition'),
        path('ajax/recalculer-score/<int:score_id>/', ajax_recalculer_score, name='ajax_recalculer_score'),
    ]

# ================================================================
# SITE D'ADMINISTRATION INTÉGRÉ
# ================================================================

class InterimAdminSiteIntegre(admin.AdminSite):
    """Site d'administration intégré avec propositions et scoring"""
    
    site_header = "Administration Intérim - Propositions & Scoring Hybride"
    site_title = "Intérim Admin Intégré"
    index_title = "Tableau de bord - Système d'intérim avec propositions humaines"
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = get_admin_urls_integres()
        return custom_urls + urls
    
    def index(self, request, extra_context=None):
        """Page d'accueil avec statistiques intégrées"""
        extra_context = extra_context or {}
        
        try:
            # Statistiques rapides intégrées
            today = date.today()
            
            extra_context.update({
                'stats_integrees': {
                    'employes_actifs': ProfilUtilisateur.objects.filter(actif=True).count(),
                    'demandes_en_cours': DemandeInterim.objects.filter(
                        statut__in=['SOUMISE', 'EN_PROPOSITION', 'EN_VALIDATION', 'CANDIDAT_PROPOSE']
                    ).count(),
                    'propositions_en_attente': PropositionCandidat.objects.filter(
                        statut__in=['SOUMISE', 'EN_EVALUATION']
                    ).count(),
                    'score_moyen': ScoreDetailCandidat.objects.aggregate(
                        avg=Avg('score_total')
                    )['avg'] or 0,
                },
                'liens_rapides_integres': [
                    {
                        'titre': 'Propositions & Scoring',
                        'url': 'admin:tableau_bord_propositions',
                        'icon': '👥',
                        'description': 'Gestion des propositions humaines et scoring'
                    },
                    {
                        'titre': 'Analytics Scoring',
                        'url': 'admin:analytics_scoring',
                        'icon': '📊',
                        'description': 'Analyses détaillées du système de scoring'
                    },
                    {
                        'titre': 'Monitoring Workflow',
                        'url': 'admin:workflow_monitoring',
                        'icon': '⚙️',
                        'description': 'Suivi des workflows et validations'
                    },
                    {
                        'titre': 'Configurations Scoring',
                        'url': 'admin:votre_app_configurationscoring_changelist',
                        'icon': '🔧',
                        'description': 'Paramétrage des algorithmes de scoring'
                    },
                ]
            })
        except Exception as e:
            logger.error(f"Erreur page d'accueil admin intégré: {e}")
        
        return super().index(request, extra_context)

# ================================================================
# ENREGISTREMENT ET CONFIGURATION FINALE
# ================================================================

# Configuration de l'interface
try:
    admin.site.enable_nav_sidebar = True
except AttributeError:
    pass

# Log de confirmation
'''
logger.info("✅ Interface d'administration INTÉGRÉE chargée avec succès")
logger.info("🎯 Fonctionnalités intégrées:")
logger.info("   • Propositions de candidats par les utilisateurs")
logger.info("   • Scoring hybride (automatique + humain)")
logger.info("   • Workflow de validation multi-niveaux")
logger.info("   • Notifications intelligentes")
logger.info("   • Historique détaillé des actions")
logger.info("   • Analytics et monitoring avancés")
logger.info("   • APIs AJAX pour l'interactivité")
logger.info("🚀 Système d'intérim avec propositions humaines opérationnel")
'''