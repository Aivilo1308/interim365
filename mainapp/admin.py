"""
Administration Django pour le système de gestion d'intérim - Version SANS CRYPTAGE
Interface d'administration avec support complet des mots de passe et hiérarchie CORRIGÉE

  Hiérarchie corrigée : RESPONSABLE → DIRECTEUR → RH/ADMIN
  Superutilisateurs avec droits complets automatiques
  Gestion complète des mots de passe utilisateur
  Interface sécurisée pour modification des mots de passe
  Validation et hachage automatique des mots de passe
  Propositions humaines intégrées au workflow
  Scoring hybride (automatique + humain) avec bonus hiérarchiques
  Tous les modèles intégrés et configurés
  Configuration Kelio SANS cryptage de mot de passe
"""

# ================================================================
# IMPORTS DJANGO CORRIGÉS
# ================================================================
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AdminPasswordChangeForm
from django.contrib.auth import update_session_auth_hash
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
from django.contrib.auth.hashers import make_password
from django.utils.safestring import mark_safe

# ================================================================
# IMPORTS DJANGO FORMS
# ================================================================
from django import forms
from django.forms import ModelForm, CharField, PasswordInput, TextInput, BooleanField

# ================================================================
# IMPORTS PYTHON STANDARDS
# ================================================================
import csv
from datetime import date, timedelta
import logging

# ================================================================
# IMPORTS DES MODÈLES
# ================================================================
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
    FormationUtilisateur, AbsenceUtilisateur, DisponibiliteUtilisateur,

    SignalementDateFerie
)

logger = logging.getLogger(__name__)

# ================================================================
# CONFIGURATION GLOBALE ADAPTÉE À LA NOUVELLE HIÉRARCHIE
# ================================================================

admin.site.site_header = "Administration Système d'Intérim - Hiérarchie RESPONSABLE → DIRECTEUR → RH/ADMIN"
admin.site.site_title = "Intérim Admin"
admin.site.index_title = "Tableau de bord - Gestion complète avec hiérarchie corrigée"

# ================================================================
# FORMULAIRES PERSONNALISÉS POUR GESTION DES MOTS DE PASSE
# ================================================================

class CustomUserCreationForm(UserCreationForm):
    """Formulaire de création d'utilisateur avec champs étendus"""
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'is_active', 'is_staff')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True
        
        # Améliorer les widgets
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Saisir le mot de passe'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirmer le mot de passe'
        })

class CustomUserChangeForm(UserChangeForm):
    """Formulaire de modification d'utilisateur avec gestion des mots de passe"""
    
    new_password1 = CharField(
        label="Nouveau mot de passe",
        widget=PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Laissez vide pour conserver le mot de passe actuel"
    )
    new_password2 = CharField(
        label="Confirmer le nouveau mot de passe",
        widget=PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Saisissez le même mot de passe pour confirmation"
    )
    
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Retirer le champ password par défaut de Django
        if 'password' in self.fields:
            del self.fields['password']
        
        # Marquer les champs requis
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['email'].required = True

    def clean_new_password2(self):
        """Validation des mots de passe"""
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        
        if password1 and password2:
            if password1 != password2:
                raise ValidationError("Les deux mots de passe ne correspondent pas.")
        elif password1 and not password2:
            raise ValidationError("Veuillez confirmer le nouveau mot de passe.")
        elif password2 and not password1:
            raise ValidationError("Veuillez saisir le nouveau mot de passe.")
            
        return password2

    def save(self, commit=True):
        """Sauvegarde avec mise à jour du mot de passe si fourni"""
        user = super().save(commit=False)
        
        # Mettre à jour le mot de passe si fourni
        new_password = self.cleaned_data.get('new_password1')
        if new_password:
            user.set_password(new_password)
        
        if commit:
            user.save()
            self.save_m2m()
        
        return user

class ProfilUtilisateurForm(ModelForm):
    """Formulaire pour ProfilUtilisateur avec gestion des mots de passe"""
    
    # Champs pour la création/modification de l'utilisateur Django
    username = CharField(
        label="Nom d'utilisateur",
        max_length=150,
        help_text="Nom d'utilisateur unique pour la connexion"
    )
    first_name = CharField(
        label="Prénom",
        max_length=150
    )
    last_name = CharField(
        label="Nom",
        max_length=150
    )
    email = CharField(
        label="Email",
        max_length=254,
        widget=TextInput(attrs={'type': 'email'})
    )
    
    # Champs pour les mots de passe
    password1 = CharField(
        label="Mot de passe",
        widget=PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Laissez vide pour conserver le mot de passe actuel (si modification)"
    )
    password2 = CharField(
        label="Confirmer le mot de passe",
        widget=PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text="Ressaisissez le mot de passe pour confirmation"
    )
    
    # Activation de l'utilisateur
    user_is_active = BooleanField(
        label="Compte actif",
        required=False,
        initial=True
    )
    
    class Meta:
        model = ProfilUtilisateur
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Si on modifie un profil existant, pré-remplir les champs utilisateur
        if self.instance and self.instance.pk and hasattr(self.instance, 'user'):
            user = self.instance.user
            self.fields['username'].initial = user.username
            self.fields['first_name'].initial = user.first_name
            self.fields['last_name'].initial = user.last_name
            self.fields['email'].initial = user.email
            self.fields['user_is_active'].initial = user.is_active
            
            # Les mots de passe ne sont pas requis en modification
            self.fields['password1'].help_text = "Laissez vide pour conserver le mot de passe actuel"
            self.fields['password2'].help_text = "Laissez vide pour conserver le mot de passe actuel"
        else:
            # En création, les mots de passe sont requis
            self.fields['password1'].required = True
            self.fields['password2'].required = True
            self.fields['password1'].help_text = "Mot de passe requis pour nouveau compte"

    def clean_username(self):
        """Validation de l'unicité du nom d'utilisateur"""
        username = self.cleaned_data.get('username')
        if username:
            # Vérifier l'unicité
            existing_users = User.objects.filter(username=username)
            if self.instance and self.instance.pk and hasattr(self.instance, 'user'):
                existing_users = existing_users.exclude(pk=self.instance.user.pk)
            
            if existing_users.exists():
                raise ValidationError("Ce nom d'utilisateur existe déjà.")
        
        return username

    def clean_email(self):
        """Validation de l'unicité de l'email"""
        email = self.cleaned_data.get('email')
        if email:
            # Vérifier l'unicité
            existing_users = User.objects.filter(email=email)
            if self.instance and self.instance.pk and hasattr(self.instance, 'user'):
                existing_users = existing_users.exclude(pk=self.instance.user.pk)
            
            if existing_users.exists():
                raise ValidationError("Cet email existe déjà.")
        
        return email

    def clean_password2(self):
        """Validation des mots de passe"""
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        # Si c'est une création, les mots de passe sont requis
        if not self.instance.pk:
            if not password1:
                raise ValidationError("Le mot de passe est requis pour un nouveau compte.")
            if not password2:
                raise ValidationError("La confirmation du mot de passe est requise.")
        
        # Si des mots de passe sont fournis, ils doivent correspondre
        if password1 and password2:
            if password1 != password2:
                raise ValidationError("Les deux mots de passe ne correspondent pas.")
        elif password1 and not password2:
            raise ValidationError("Veuillez confirmer le nouveau mot de passe.")
        elif password2 and not password1:
            raise ValidationError("Veuillez saisir le nouveau mot de passe.")
            
        return password2

    def save(self, commit=True):
        """Sauvegarde avec création/mise à jour de l'utilisateur Django SYNCHRONISÉ"""
        profil = super().save(commit=False)
        
        # Récupérer les données utilisateur du formulaire
        username = self.cleaned_data.get('username')
        first_name = self.cleaned_data.get('first_name')
        last_name = self.cleaned_data.get('last_name')
        email = self.cleaned_data.get('email')
        password = self.cleaned_data.get('password1')
        is_active = self.cleaned_data.get('user_is_active', True)
        
        # Créer ou mettre à jour l'utilisateur Django
        if profil.pk and hasattr(profil, 'user'):
            # Modification d'un profil existant
            user = profil.user
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.email = email
            user.is_active = bool(is_active)
            
            #   SYNCHRONISATION : Mettre à jour le mot de passe si fourni
            if password:
                user.set_password(password)
                
        else:
            # Création d'un nouveau profil
            user = User.objects.create_user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                password=password,
                is_active=bool(is_active)
            )
            profil.user = user
        
        if commit:
            user.save()
            profil.save()
            
            #   SYNCHRONISATION BIDIRECTIONNELLE
            profil.sync_with_user(commit=True)
            
            self.save_m2m()
        
        return profil

# ================================================================
# FORMULAIRE SIMPLIFIÉ POUR ConfigurationApiKelio (SANS CRYPTAGE)
# ================================================================

class ConfigurationApiKelioForm(ModelForm):
    """Formulaire simple pour ConfigurationApiKelio SANS cryptage du mot de passe"""
    
    class Meta:
        model = ConfigurationApiKelio
        fields = '__all__'
        widgets = {
            'password': PasswordInput(attrs={
                'class': 'form-control',
                'placeholder': 'Saisir le mot de passe en clair'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Personnaliser les widgets et labels
        self.fields['password'].help_text = "Mot de passe stocké en clair (non crypté)"
        
        if self.instance and self.instance.pk:
            # En modification, afficher une indication si un mot de passe existe
            if self.instance.password:
                self.fields['password'].help_text = "Mot de passe actuel défini. Modifiez pour changer."
        else:
            # En création, le mot de passe est requis
            self.fields['password'].required = True
            self.fields['password'].help_text = "Mot de passe requis pour nouvelle configuration"

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

def format_boolean_display(value, true_icon=" ", false_icon="❌"):
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

class ReadOnlyModelAdmin(ReadOnlyMixin, BaseModelAdmin):
    """Admin en lecture seule basé sur BaseModelAdmin"""
    pass

# ================================================================
# ADMIN UTILISATEUR PERSONNALISÉ AVEC GESTION DES MOTS DE PASSE
# ================================================================

class CustomUserAdmin(UserAdmin):
    """Administration des utilisateurs Django avec gestion complète des mots de passe"""
    
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    list_display = (
        'username', 'display_full_name', 'email', 'display_status', 
        'display_staff_status', 'display_superuser_status', 'display_last_login', 'date_joined'
    )
    list_filter = ('is_active', 'is_staff', 'is_superuser', 'date_joined', 'last_login')
    search_fields = ('username', 'first_name', 'last_name', 'email')
    ordering = ('username',)
    
    fieldsets = (
        ('Informations de connexion', {
            'fields': ('username', 'new_password1', 'new_password2')
        }),
        ('Informations personnelles', {
            'fields': ('first_name', 'last_name', 'email')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Dates importantes', {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )
    
    add_fieldsets = (
        ('Création d\'utilisateur', {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'is_active', 'is_staff'),
        }),
    )
    
    readonly_fields = ('last_login', 'date_joined')
    
    actions = ['activate_users', 'deactivate_users', 'reset_passwords']
    
    def display_full_name(self, obj):
        """Affiche le nom complet"""
        full_name = f"{obj.first_name} {obj.last_name}".strip()
        return full_name if full_name else obj.username
    display_full_name.short_description = "Nom complet"
    
    def display_status(self, obj):
        """Affiche le statut actif/inactif"""
        return format_status_display(obj.is_active)
    display_status.short_description = "Statut"
    
    def display_staff_status(self, obj):
        """Affiche le statut staff"""
        return format_boolean_display(obj.is_staff, "👔 Staff", "👤 Utilisateur")
    display_staff_status.short_description = "Staff"
    
    def display_superuser_status(self, obj):
        """Affiche le statut superuser - ADAPTÉ À LA NOUVELLE HIÉRARCHIE"""
        if obj.is_superuser:
            return format_html('<span style="color: purple; font-weight: bold;">  Superuser - Droits complets</span>')
        return format_html('<span style="color: gray;">👤 Normal</span>')
    display_superuser_status.short_description = "Superuser"
    
    def display_last_login(self, obj):
        """Affiche la dernière connexion"""
        if obj.last_login:
            delta = timezone.now() - obj.last_login
            if delta.days == 0:
                return "Aujourd'hui"
            elif delta.days == 1:
                return "Hier"
            elif delta.days < 7:
                return f"Il y a {delta.days} jours"
            else:
                return obj.last_login.strftime('%d/%m/%Y')
        return "Jamais"
    display_last_login.short_description = "Dernière connexion"
    
    def save_model(self, request, obj, form, change):
        """Sauvegarde avec gestion des mots de passe"""
        # Le formulaire CustomUserChangeForm s'occupe déjà de la gestion des mots de passe
        super().save_model(request, obj, form, change)
        
        # Maintenir la session si l'utilisateur change son propre mot de passe
        if change and obj == request.user and 'new_password1' in form.cleaned_data and form.cleaned_data['new_password1']:
            update_session_auth_hash(request, obj)
    
    def activate_users(self, request, queryset):
        """Active les utilisateurs sélectionnés"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} utilisateur(s) activé(s).")
    activate_users.short_description = "Activer les utilisateurs"
    
    def deactivate_users(self, request, queryset):
        """Désactive les utilisateurs sélectionnés"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} utilisateur(s) désactivé(s).")
    deactivate_users.short_description = "Désactiver les utilisateurs"
    
    def reset_passwords(self, request, queryset):
        """Redirection vers une page de réinitialisation des mots de passe"""
        if queryset.count() > 5:
            self.message_user(request, "Impossible de réinitialiser plus de 5 mots de passe à la fois.", level=messages.ERROR)
            return
        
        user_ids = list(queryset.values_list('id', flat=True))
        return redirect('admin:reset_multiple_passwords', user_ids=','.join(map(str, user_ids)))
    reset_passwords.short_description = "Réinitialiser les mots de passe"

# Remplacer l'admin User par défaut
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

# ================================================================
# ADMIN PROFIL UTILISATEUR AVEC HIÉRARCHIE CORRIGÉE
# ================================================================

@admin.register(ProfilUtilisateur)
class ProfilUtilisateurAdmin(BaseModelAdmin):
    """Administration des profils utilisateur avec hiérarchie CORRIGÉE"""
    
    form = ProfilUtilisateurForm
    
    list_display = (
        'matricule', 'nom_complet', 'display_user_info', 'departement', 'poste', 
        'display_type_profil_hierarchique', 'status_display', 'display_disponible_interim', 
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
        ('Informations personnelles', {
            'fields': ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'user_is_active')
        }),
        ('Profil employé', {
            'fields': ('matricule', 'type_profil', 'departement', 'site', 'poste', 'manager', 'statut_employe', 'actif')
        }),
        ('Données Kelio', {
            'fields': ('kelio_employee_key', 'kelio_badge_code'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_type_profil_hierarchique(self, obj):
        """Affiche le type de profil avec hiérarchie"""
        if obj.user and obj.user.is_superuser:
            return format_html('<strong style="color: purple;">  SUPERUSER</strong>')
        
        types = {
            'UTILISATEUR': ('👤', 'gray'),
            'CHEF_EQUIPE': (' ', 'blue'),
            'RESPONSABLE': ('👔', 'green'),  #   Niveau 1
            'DIRECTEUR': ('🏢', 'orange'),   #   Niveau 2
            'RH': ('👨‍💼', 'red'),             #   Niveau 3
            'ADMIN': ('⚙️', 'purple'),       #   Niveau 3 étendu
        }
        
        icon, couleur = types.get(obj.type_profil, ('❓', 'gray'))
        return format_html(
            '<strong style="color: {};">{} {}</strong>',
            couleur, icon, obj.type_profil
        )
    display_type_profil_hierarchique.short_description = "Type profil"
    
    def status_display(self, obj):
        return format_status_display(obj.actif)
    status_display.short_description = "Statut"
    
    def display_disponible_interim(self, obj):
        try:
            if hasattr(obj, 'extended_data') and obj.extended_data.disponible_interim:
                return format_html('<span style="color: green;">  Disponible</span>')
            else:
                return format_html('<span style="color: red;">❌ Non disponible</span>')
        except:
            return format_html('<span style="color: gray;">❓ Non défini</span>')
    display_disponible_interim.short_description = "Intérim"

    def save_model(self, request, obj, form, change):
        """Sauvegarde avec synchronisation des mots de passe"""
        # Le formulaire ProfilUtilisateurForm gère déjà la synchronisation
        super().save_model(request, obj, form, change)
        
        # Log pour audit
        if change:
            logger.info(f"Profil utilisateur {obj.matricule} modifié par {request.user.username}")
        else:
            logger.info(f"Profil utilisateur {obj.matricule} créé par {request.user.username}")

    def display_user_info(self, obj):
        """Affiche les informations utilisateur synchronisées"""
        if obj.user:
            statut = "🟢 Actif" if obj.user.is_active else "🔴 Inactif"
            return format_html(
                '<strong>{}</strong><br/>'
                '<small>👤 {} | 📧 {}</small><br/>'
                '<small>{}</small>',
                obj.user.username,
                obj.nom_complet,
                obj.user.email or "Pas d'email",
                statut
            )
        else:
            return format_html('<span style="color: red;">❌ Pas d\'utilisateur Django associé</span>')
    display_user_info.short_description = "Utilisateur Django"

    def display_sync_status(self, obj):
        """Affiche le statut de synchronisation"""
        if obj.user:
            return format_html('<span style="color: green;">🔄 Synchronisé</span>')
        else:
            return format_html('<span style="color: red;">❌ Non synchronisé</span>')
    display_sync_status.short_description = "Synchronisation"

# ================================================================
# ADMIN POUR CONFIGURATION KELIO SIMPLIFIÉ (SANS CRYPTAGE)
# ================================================================

@admin.register(ConfigurationApiKelio)
class ConfigurationApiKelioAdmin(BaseModelAdmin):
    """Administration simplifiée SANS cryptage du mot de passe"""
    
    form = ConfigurationApiKelioForm  #   Utiliser le formulaire simplifié
    
    list_display = ('nom', 'url_base', 'username', 'display_password_status', 'display_status', 'display_services', 'created_at')
    list_filter = ('actif', 'service_employees', 'service_absences')
    search_fields = ('nom', 'url_base', 'username')
    
    fieldsets = (
        ('Configuration de base', {
            'fields': ('nom', 'url_base', 'username', 'password', 'actif')
        }),
        ('Paramètres connexion', {
            'fields': ('timeout_seconds',),
            'classes': ('collapse',)
        }),
        ('Services disponibles', {
            'fields': (
                ('service_employees', 'service_absences'),
                ('service_formations', 'service_competences')
            )
        }),
        ('Configuration cache', {
            'fields': (
                ('cache_duree_defaut_minutes', 'cache_taille_max_mo'),
                'auto_invalidation_cache'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def display_password_status(self, obj):
        """Affiche le statut du mot de passe (SANS CRYPTAGE)"""
        if obj.password:
            return format_html('<span style="color: green;">🔐 Configuré (clair)</span>')
        else:
            return format_html('<span style="color: red;">❌ Non configuré</span>')
    display_password_status.short_description = "Mot de passe"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_services(self, obj):
        services = []
        if obj.service_employees: services.append(" ")
        if obj.service_absences: services.append("📅")
        if obj.service_formations: services.append("📚")
        if obj.service_competences: services.append(" ")
        return "".join(services) if services else "❌"
    display_services.short_description = "Services"
    
    actions = ['test_connexion', 'vider_caches']
    
    def test_connexion(self, request, queryset):
        """Action pour tester la connexion Kelio"""
        for config in queryset:
            try:
                # Maintenant le mot de passe est accessible directement (pas de décryptage)
                if config.password:
                    self.message_user(request, f"  Configuration {config.nom} - Mot de passe défini")
                else:
                    self.message_user(request, f"❌ Mot de passe manquant pour {config.nom}", level=messages.ERROR)
            except Exception as e:
                self.message_user(request, f"❌ Erreur test connexion {config.nom}: {str(e)}", level=messages.ERROR)
    test_connexion.short_description = "Tester la configuration"
    
    def vider_caches(self, request, queryset):
        """Action pour vider les caches"""
        total_cleared = 0
        for config in queryset:
            try:
                cleared = config.vider_cache()
                total_cleared += cleared
            except Exception:
                pass
        
        self.message_user(request, f"🗑️ {total_cleared} entrées de cache supprimées")
    vider_caches.short_description = "Vider les caches"

# ================================================================
# ADMIN POUR CONFIGURATION SCORING
# ================================================================

@admin.register(ConfigurationScoring)
class ConfigurationScoringAdmin(BaseModelAdmin):
    """Administration des configurations de scoring avec bonus hiérarchiques"""
    
    list_display = (
        'nom', 'display_status', 'display_default', 'display_bonus_hierarchiques', 
        'nb_utilisations', 'last_used', 'created_by'
    )
    list_filter = ('actif', 'configuration_par_defaut', 'created_by')
    search_fields = ('nom', 'description')
    readonly_fields = ('created_at', 'updated_at', 'nb_utilisations', 'last_used')
    
    fieldsets = (
        ('Configuration de base', {
            'fields': ('nom', 'description', 'actif', 'configuration_par_defaut')
        }),
        ('Pondérations principales (total = 1.0)', {
            'fields': (
                ('poids_similarite_poste', 'poids_competences'),
                ('poids_experience', 'poids_disponibilite'),
                ('poids_proximite', 'poids_anciennete')
            ),
            'description': 'La somme de tous les poids doit être égale à 1.0'
        }),
        ('Bonus généraux', {
            'fields': (
                ('bonus_proposition_humaine', 'bonus_experience_similaire'),
                'bonus_recommandation'
            )
        }),
        ('Bonus hiérarchiques CORRIGÉS', {
            'fields': (
                ('bonus_manager_direct', 'bonus_chef_equipe'),
                ('bonus_responsable', 'bonus_directeur'),
                ('bonus_rh', 'bonus_admin'),
                'bonus_superuser'
            ),
            'description': 'Bonus selon le niveau hiérarchique du proposant : RESPONSABLE → DIRECTEUR → RH/ADMIN'
        }),
        ('Pénalités', {
            'fields': (
                ('penalite_indisponibilite_partielle', 'penalite_indisponibilite_totale'),
                'penalite_distance_excessive'
            ),
            'classes': ('collapse',)
        }),
        ('Restrictions', {
            'fields': ('pour_departements', 'pour_types_urgence'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'nb_utilisations', 'last_used', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_default(self, obj):
        if obj.configuration_par_defaut:
            return format_html('<span style="color: blue; font-weight: bold;">⭐ Par défaut</span>')
        return format_html('<span style="color: gray;">-</span>')
    display_default.short_description = "Défaut"
    
    def display_bonus_hierarchiques(self, obj):
        """Affiche un résumé des bonus hiérarchiques"""
        bonus_info = [
            f"RESP:{obj.bonus_responsable}",
            f"DIR:{obj.bonus_directeur}",
            f"RH:{obj.bonus_rh}",
            f"ADM:{obj.bonus_admin}"
        ]
        return " | ".join(bonus_info)
    display_bonus_hierarchiques.short_description = "Bonus hiérarchiques"

# ================================================================
# ADMIN PROPOSITION CANDIDAT AVEC HIÉRARCHIE CORRIGÉE
# ================================================================

@admin.register(PropositionCandidat)
class PropositionCandidatAdmin(BaseModelAdmin):
    list_display = (
        'numero_proposition', 'candidat_propose', 'display_proposant_hierarchique', 'demande_interim',
        'display_source_hierarchique', 'display_statut', 'display_score_avec_bonus_hierarchique', 'created_at'
    )
    list_filter = ('statut', 'source_proposition', 'demande_interim__urgence', 'niveau_validation_propose')
    search_fields = ('numero_proposition', 'candidat_propose__matricule', 'proposant__matricule', 'demande_interim__numero_demande')
    readonly_fields = ('numero_proposition', 'created_at', 'updated_at', 'score_final')
    
    fieldsets = (
        ('Informations générales', {
            'fields': (
                'numero_proposition', 'demande_interim', 
                ('candidat_propose', 'proposant'),
                'source_proposition', 'niveau_validation_propose'
            )
        }),
        ('Justification', {
            'fields': (
                'justification', 'competences_specifiques', 'experience_pertinente'
            )
        }),
        ('Scoring avec bonus hiérarchiques CORRIGÉ', {
            'fields': (
                'statut',
                ('score_automatique', 'score_humain_ajuste'),
                'bonus_proposition_humaine',
                'score_final'
            ),
            'description': 'Score final = Score base + Bonus hiérarchique selon niveau proposant'
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
    
    def display_proposant_hierarchique(self, obj):
        """Affiche le proposant avec son niveau hiérarchique"""
        if obj.proposant:
            if obj.proposant.is_superuser:
                return format_html('<strong style="color: purple;">  {} (SUPERUSER)</strong>', obj.proposant.nom_complet)
            
            niveaux = {
                'UTILISATEUR': ('👤', 'gray'),
                'CHEF_EQUIPE': (' ', 'blue'),
                'RESPONSABLE': ('👔', 'green'),  #   Niveau 1
                'DIRECTEUR': ('🏢', 'orange'),   #   Niveau 2
                'RH': ('👨‍💼', 'red'),             #   Niveau 3
                'ADMIN': ('⚙️', 'purple'),       #   Niveau 3 étendu
            }
            
            icon, couleur = niveaux.get(obj.proposant.type_profil, ('❓', 'gray'))
            return format_html(
                '<strong style="color: {};">{} {} ({})</strong>',
                couleur, icon, obj.proposant.nom_complet, obj.proposant.type_profil
            )
        return "❌ Proposant non défini"
    display_proposant_hierarchique.short_description = "Proposant (niveau)"
    
    def display_source_hierarchique(self, obj):
        """Affiche la source selon la hiérarchie CORRIGÉE"""
        sources = {
            'DEMANDEUR_INITIAL': ('👤 Demandeur', 'blue'),
            'MANAGER_DIRECT': ('  Manager', 'blue'),
            'CHEF_EQUIPE': ('👷 Chef équipe', 'blue'),
            'RESPONSABLE': ('👔 RESPONSABLE (N+1)', 'green'),     #   Niveau 1
            'DIRECTEUR': ('🏢 DIRECTEUR (N+2)', 'orange'),        #   Niveau 2
            'RH': ('👨‍💼 RH (Final)', 'red'),                     #   Niveau 3
            'ADMIN': ('⚙️ ADMIN (Final)', 'purple'),              #   Niveau 3 étendu
            'SUPERUSER': ('  SUPERUSER', 'purple'),            #   Droits complets
            'VALIDATION_ETAPE': ('⚖️ Validation', 'gray'),
            'SYSTEME': ('🤖 Système', 'gray'),
            'AUTRE': ('❓ Autre', 'gray')
        }
        texte, couleur = sources.get(obj.source_proposition, ('❓ Non défini', 'gray'))
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', couleur, texte)
    display_source_hierarchique.short_description = "Source hiérarchique"
    
    def display_statut(self, obj):
        """Affiche le statut avec couleurs"""
        statuts = {
            'SOUMISE': '<span style="color: blue;">📝 Soumise</span>',
            'EN_EVALUATION': '<span style="color: orange;">🔍 En évaluation</span>',
            'EVALUEE': '<span style="color: green;">  Évaluée</span>',
            'RETENUE': '<span style="color: purple;">⭐ Retenue</span>',
            'REJETEE': '<span style="color: red;">❌ Rejetée</span>',
            'VALIDEE': '<span style="color: green; font-weight: bold;">  Validée</span>',
        }
        return format_html(statuts.get(obj.statut, obj.statut))
    display_statut.short_description = "Statut"
    
    def display_score_avec_bonus_hierarchique(self, obj):
        """Affiche le score avec détail du bonus hiérarchique"""
        score_base = obj.score_humain_ajuste or obj.score_automatique or 0
        bonus = obj.bonus_proposition_humaine
        score_final = obj.score_final
        
        if score_final is None:
            return format_html('<span style="color: gray;">❓ Non calculé</span>')
        
        # Couleur selon le score
        if score_final >= 80:
            color = 'green'
            icon = '🟢'
        elif score_final >= 60:
            color = 'orange'
            icon = '🟡'
        else:
            color = 'red'
            icon = '🔴'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}/100</span><br/>'
            '<small>Base: {} + Bonus hier.: +{}</small>',
            color, icon, score_final, score_base, bonus
        )
    display_score_avec_bonus_hierarchique.short_description = "Score (avec bonus hier.)"

# ================================================================
# ADMIN VALIDATION DEMANDE AVEC HIÉRARCHIE CORRIGÉE
# ================================================================

@admin.register(ValidationDemande)
class ValidationDemandeAdmin(BaseModelAdmin):
    list_display = (
        'demande', 'display_type_validation_hierarchique', 'display_validateur_niveau', 
        'display_decision', 'display_statut', 'date_demande_validation'
    )
    list_filter = ('decision', 'type_validation', 'niveau_validation', 'date_validation')
    search_fields = ('demande__numero_demande', 'validateur__matricule')
    readonly_fields = ('date_demande_validation', 'delai_traitement')
    
    fieldsets = (
        ('Validation hiérarchique CORRIGÉE', {
            'fields': (
                'demande', 'type_validation', 'niveau_validation',
                'validateur', 'decision'
            ),
            'description': 'Niveau 1: RESPONSABLE | Niveau 2: DIRECTEUR | Niveau 3: RH/ADMIN'
        }),
        ('Détails', {
            'fields': ('commentaire',)
        }),
        ('Candidats traités', {
            'fields': (
                'candidats_retenus', 'candidats_rejetes',
                'nouveau_candidat_propose', 'justification_nouveau_candidat'
            ),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('date_demande_validation', 'date_validation'),
            'classes': ('collapse',)
        })
    )
    
    def display_type_validation_hierarchique(self, obj):
        """Affiche le type de validation selon la hiérarchie CORRIGÉE"""
        types = {
            'RESPONSABLE': '<span style="color: green; font-weight: bold;">👔 RESPONSABLE (N+1)</span>',
            'DIRECTEUR': '<span style="color: orange; font-weight: bold;">🏢 DIRECTEUR (N+2)</span>',
            'RH': '<span style="color: red; font-weight: bold;">👨‍💼 RH (Final)</span>',
            'ADMIN': '<span style="color: purple; font-weight: bold;">⚙️ ADMIN (Final)</span>',
            'SUPERUSER': '<span style="color: purple; font-weight: bold;">  SUPERUSER</span>',
            'URGENCE': '<span style="color: red; font-weight: bold;">🚨 URGENCE</span>'
        }
        return format_html(types.get(obj.type_validation, '❓ Type inconnu'))
    display_type_validation_hierarchique.short_description = "Type validation"
    
    def display_validateur_niveau(self, obj):
        """Affiche le validateur avec son niveau"""
        if obj.validateur:
            if obj.validateur.is_superuser:
                return format_html('<strong style="color: purple;">  {} (SUPERUSER)</strong>', obj.validateur.nom_complet)
            
            return format_html(
                '<strong>{}</strong><br/><small>Niveau {} - {}</small>',
                obj.validateur.nom_complet,
                obj.niveau_validation,
                obj.validateur.type_profil
            )
        return "❌ Validateur non défini"
    display_validateur_niveau.short_description = "Validateur (niveau)"
    
    def display_decision(self, obj):
        return obj.decision_display
    display_decision.short_description = "Décision"
    
    def display_statut(self, obj):
        if obj.en_attente:
            return format_html('<span style="color: orange;">⏳ En attente</span>')
        else:
            return format_html('<span style="color: green;">  Traitée</span>')
    display_statut.short_description = "Statut"

# ================================================================
# ADMINS ORGANISATIONNELS
# ================================================================

@admin.register(Departement)
class DepartementAdmin(BaseModelAdmin):
    list_display = ('nom', 'code', 'manager', 'display_status', 'employes_count')
    list_filter = ('actif',)
    search_fields = ('nom', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at', 'kelio_last_sync')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'description', 'code', 'manager', 'actif')
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_department_key', 'kelio_last_sync'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"

@admin.register(Site)
class SiteAdmin(BaseModelAdmin):
    list_display = ('nom', 'ville', 'code_postal', 'responsable', 'display_status', 'display_contact')
    list_filter = ('actif', 'ville', 'pays')
    search_fields = ('nom', 'ville', 'code_postal', 'adresse')
    readonly_fields = ('created_at', 'updated_at', 'kelio_last_sync')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'responsable', 'actif')
        }),
        ('Adresse', {
            'fields': ('adresse', 'ville', 'code_postal', 'pays')
        }),
        ('Contact', {
            'fields': ('telephone', 'email')
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_site_key', 'kelio_last_sync'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_contact(self, obj):
        contact = []
        if obj.telephone:
            contact.append(f"📞 {obj.telephone}")
        if obj.email:
            contact.append(f"📧 {obj.email}")
        return " | ".join(contact) if contact else "Aucun"
    display_contact.short_description = "Contact"

@admin.register(Poste)
class PosteAdmin(BaseModelAdmin):
    list_display = ('titre', 'departement', 'site', 'niveau_responsabilite_display', 'display_status', 'display_interim_info')
    list_filter = ('actif', 'departement', 'site', 'niveau_responsabilite', 'interim_autorise')
    search_fields = ('titre', 'description', 'departement__nom', 'site__nom')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('titre', 'description', 'departement', 'site', 'actif')
        }),
        ('Caractéristiques du poste', {
            'fields': (
                'niveau_responsabilite', 'categorie',
                ('niveau_etude_min', 'experience_min_mois'),
                'permis_requis', 'interim_autorise'
            )
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_job_key',),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_interim_info(self, obj):
        if obj.interim_autorise:
            return format_html('<span style="color: green;">  Autorisé</span>')
        else:
            return format_html('<span style="color: red;">❌ Non autorisé</span>')
    display_interim_info.short_description = "Intérim"

# ================================================================
# ADMIN COMPÉTENCES
# ================================================================

@admin.register(Competence)
class CompetenceAdmin(BaseModelAdmin):
    list_display = ('nom', 'type_competence', 'categorie', 'display_status', 'display_utilisation')
    list_filter = ('actif', 'type_competence', 'obsolete', 'categorie')
    search_fields = ('nom', 'description', 'categorie')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'description', 'type_competence', 'categorie', 'actif', 'obsolete')
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_skill_key', 'kelio_skill_abbreviation'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        if obj.obsolete:
            return format_html('<span style="color: orange;">⚠️ Obsolète</span>')
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_utilisation(self, obj):
        try:
            nb_utilisateurs = obj.competences_utilisateurs.count()
            return f"{nb_utilisateurs} utilisateur(s)"
        except:
            return "N/A"
    display_utilisation.short_description = "Utilisation"

@admin.register(CompetenceUtilisateur)
class CompetenceUtilisateurAdmin(BaseModelAdmin):
    list_display = ('utilisateur', 'competence', 'display_niveau', 'display_source', 'display_certification', 'updated_at')
    list_filter = ('niveau_maitrise', 'source_donnee', 'certifie', 'competence__type_competence')
    search_fields = ('utilisateur__matricule', 'utilisateur__user__first_name', 'competence__nom')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Association', {
            'fields': ('utilisateur', 'competence', 'niveau_maitrise', 'source_donnee')
        }),
        ('Évaluation', {
            'fields': (
                ('date_acquisition', 'date_evaluation'),
                'evaluateur', 'commentaire'
            )
        }),
        ('Certification', {
            'fields': (
                'certifie', 'date_certification', 'organisme_certificateur'
            ),
            'classes': ('collapse',)
        }),
        ('Kelio', {
            'fields': ('kelio_skill_assignment_key', 'kelio_level'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_niveau(self, obj):
        niveaux = {
            1: '🔴 Débutant',
            2: '🟡 Intermédiaire', 
            3: '🟢 Confirmé',
            4: '🟣 Expert'
        }
        return niveaux.get(obj.niveau_maitrise, '❓ Non défini')
    display_niveau.short_description = "Niveau"
    
    def display_source(self, obj):
        sources = {
            'LOCAL': '💻 Local',
            'KELIO': '🔄 Kelio',
            'MIXTE': '🔀 Mixte'
        }
        return sources.get(obj.source_donnee, obj.source_donnee)
    display_source.short_description = "Source"
    
    def display_certification(self, obj):
        if obj.certifie:
            return format_html('<span style="color: green;">🏆 Certifié</span>')
        return format_html('<span style="color: gray;">❌ Non certifié</span>')
    display_certification.short_description = "Certification"

# ================================================================
# ADMIN DEMANDES INTÉRIM AVEC HIÉRARCHIE
# ================================================================

@admin.register(DemandeInterim)
class DemandeInterimAdmin(BaseModelAdmin):
    list_display = (
        'numero_demande', 'demandeur', 'personne_remplacee', 'poste', 
        'display_urgence', 'statut', 'display_progression_validation', 'created_at'
    )
    list_filter = ('statut', 'urgence', 'poste__departement', 'created_at')
    search_fields = ('numero_demande', 'demandeur__matricule', 'personne_remplacee__matricule')
    readonly_fields = ('numero_demande', 'created_at', 'updated_at', 'duree_mission')
    ordering = ('-id',) 
    
    fieldsets = (
        ('Demande', {
            'fields': (
                'numero_demande', 'demandeur', 'personne_remplacee',
                'poste', 'motif_absence', 'urgence', 'statut'
            )
        }),
        ('Période', {
            'fields': (
                ('date_debut', 'date_fin'),
                'duree_mission'
            )
        }),
        ('Description', {
            'fields': (
                'description_poste', 'instructions_particulieres',
                'competences_indispensables'
            )
        }),
        ('Validation hiérarchique CORRIGÉE', {
            'fields': (
                ('niveau_validation_actuel', 'niveaux_validation_requis'),
                'candidat_selectionne'
            ),
            'description': 'Progression : Niveau 1 (RESPONSABLE) → Niveau 2 (DIRECTEUR) → Niveau 3 (RH/ADMIN)'
        }),
        ('Configuration workflow', {
            'fields': (
                'propositions_autorisees',
                ('nb_max_propositions_par_utilisateur', 'date_limite_propositions')
            ),
            'classes': ('collapse',)
        }),
        ('Scoring', {
            'fields': (
                ('poids_scoring_automatique', 'poids_scoring_humain'),
            ),
            'classes': ('collapse',)
        }),
        ('Dates importantes', {
            'fields': (
                ('date_validation', 'date_debut_effective', 'date_fin_effective'),
            ),
            'classes': ('collapse',)
        }),
        ('Évaluation', {
            'fields': (
                ('evaluation_mission', 'commentaire_final'),
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_urgence(self, obj):
        return format_urgence_display(obj.urgence)
    display_urgence.short_description = "Urgence"
    
    def display_progression_validation(self, obj):
        """Affiche la progression de validation hiérarchique - CORRIGÉ"""
        try:
            niveau_actuel = obj.niveau_validation_actuel or 0
            niveau_requis = obj.niveaux_validation_requis or 0
            
            if niveau_requis == 0:
                return format_html('<span style="color: gray;">❓ Non défini</span>')
            
            # Calculer la progression
            progression = (niveau_actuel / niveau_requis) * 100
            
            # Formatage sécurisé des nombres
            niveau_actuel_str = str(niveau_actuel)
            niveau_requis_str = str(niveau_requis)
            progression_str = "{:.0f}".format(progression)
            
            # Retourner le HTML formaté selon la progression
            if progression >= 100:
                return format_html(
                    '<span style="color: green; font-weight: bold;">✅ {}/{} (100%)</span>', 
                    niveau_actuel_str, niveau_requis_str
                )
            elif progression >= 66:
                return format_html(
                    '<span style="color: blue; font-weight: bold;">🔵 {}/{} ({}%)</span>', 
                    niveau_actuel_str, niveau_requis_str, progression_str
                )
            elif progression >= 33:
                return format_html(
                    '<span style="color: orange; font-weight: bold;">🟡 {}/{} ({}%)</span>', 
                    niveau_actuel_str, niveau_requis_str, progression_str
                )
            else:
                return format_html(
                    '<span style="color: red; font-weight: bold;">🔴 {}/{} ({}%)</span>', 
                    niveau_actuel_str, niveau_requis_str, progression_str
                )
                
        except (AttributeError, TypeError, ZeroDivisionError, ValueError) as e:
            # En cas d'erreur, retourner un affichage sécurisé
            return format_html('<span style="color: gray;">❓ Erreur calcul</span>')
    
    display_progression_validation.short_description = "Progression validation"

# ================================================================
# ADMIN MOTIFS ABSENCE
# ================================================================

@admin.register(MotifAbsence)
class MotifAbsenceAdmin(BaseModelAdmin):
    list_display = ('nom', 'code', 'categorie', 'display_status', 'display_contraintes', 'display_utilisation')
    list_filter = ('actif', 'categorie', 'necessite_justificatif')
    search_fields = ('nom', 'code', 'description')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('nom', 'description', 'code', 'categorie', 'couleur', 'actif')
        }),
        ('Contraintes', {
            'fields': (
                'necessite_justificatif',
                ('delai_prevenance_jours', 'duree_max_jours')
            )
        }),
        ('Synchronisation Kelio', {
            'fields': ('kelio_absence_type_key', 'kelio_abbreviation'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_contraintes(self, obj):
        contraintes = []
        if obj.necessite_justificatif:
            contraintes.append("📄 Justificatif")
        if obj.delai_prevenance_jours > 0:
            contraintes.append(f"⏰ {obj.delai_prevenance_jours}j préavis")
        if obj.duree_max_jours:
            contraintes.append(f"📅 Max {obj.duree_max_jours}j")
        return " | ".join(contraintes) if contraintes else "Aucune"
    display_contraintes.short_description = "Contraintes"
    
    def display_utilisation(self, obj):
        try:
            nb_demandes = obj.demandes.count()
            return f"{nb_demandes} demande(s)"
        except:
            return "N/A"
    display_utilisation.short_description = "Utilisation"

# ================================================================
# ADMIN WORKFLOW AVEC HIÉRARCHIE ADAPTÉE
# ================================================================

@admin.register(WorkflowEtape)
class WorkflowEtapeAdmin(BaseModelAdmin):
    list_display = ('ordre', 'nom', 'display_type_etape_hierarchique', 'display_status', 'display_contraintes', 'display_propositions')
    list_filter = ('actif', 'type_etape', 'obligatoire', 'permet_propositions_humaines')
    search_fields = ('nom', 'type_etape')
    ordering = ('ordre',)
    
    fieldsets = (
        ('Étape', {
            'fields': ('nom', 'type_etape', 'ordre', 'obligatoire', 'actif')
        }),
        ('Configuration', {
            'fields': (
                'delai_max_heures', 'condition_urgence'
            )
        }),
        ('Propositions', {
            'fields': (
                'permet_propositions_humaines',
                'permet_ajout_nouveaux_candidats'
            )
        })
    )
    
    def display_type_etape_hierarchique(self, obj):
        """Affiche le type d'étape avec hiérarchie CORRIGÉE"""
        types = {
            'DEMANDE': '📝 Création de demande',
            'PROPOSITION_CANDIDATS': '  Proposition de candidats',
            'VALIDATION_RESPONSABLE': '👔 Validation RESPONSABLE (N+1)',     #   Niveau 1
            'VALIDATION_DIRECTEUR': '🏢 Validation DIRECTEUR (N+2)',         #   Niveau 2
            'VALIDATION_RH_ADMIN': '👨‍💼 Validation RH/ADMIN (Final)',        #   Niveau 3
            'NOTIFICATION_CANDIDAT': '📧 Notification candidat',
            'ACCEPTATION_CANDIDAT': '  Acceptation candidat',
            'FINALISATION': '🏁 Finalisation',
        }
        return format_html(types.get(obj.type_etape, '❓ Type inconnu'))
    display_type_etape_hierarchique.short_description = "Type étape"
    
    def display_status(self, obj):
        return format_status_display(obj.actif)
    display_status.short_description = "Statut"
    
    def display_contraintes(self, obj):
        contraintes = []
        if obj.obligatoire:
            contraintes.append("⚡ Obligatoire")
        if obj.delai_max_heures:
            contraintes.append(f"⏰ {obj.delai_max_heures}h max")
        if obj.condition_urgence != 'TOUTES':
            contraintes.append(f"🚨 {obj.condition_urgence}")
        return " | ".join(contraintes) if contraintes else "Aucune"
    display_contraintes.short_description = "Contraintes"
    
    def display_propositions(self, obj):
        propositions = []
        if obj.permet_propositions_humaines:
            propositions.append("  Propositions")
        if obj.permet_ajout_nouveaux_candidats:
            propositions.append("➕ Nouveaux candidats")
        return " | ".join(propositions) if propositions else "❌ Aucune"
    display_propositions.short_description = "Propositions autorisées"

# ================================================================
# ADMIN NOTIFICATIONS ET HISTORIQUE AVEC HIÉRARCHIE
# ================================================================

@admin.register(NotificationInterim)
class NotificationInterimAdmin(ReadOnlyModelAdmin):
    list_display = (
        'titre', 'destinataire', 'type_display', 'urgence_display', 
        'statut', 'demande', 'created_at'
    )
    list_filter = ('statut', 'type_notification', 'urgence', 'created_at')
    search_fields = ('titre', 'message', 'destinataire__matricule', 'demande__numero_demande')
    readonly_fields = ('created_at', 'updated_at', 'date_lecture', 'date_traitement')
    
    fieldsets = (
        ('Notification', {
            'fields': (
                'destinataire', 'expediteur', 'demande',
                'type_notification', 'urgence', 'statut'
            )
        }),
        ('Contenu', {
            'fields': ('titre', 'message')
        }),
        ('Actions', {
            'fields': (
                'url_action_principale', 'texte_action_principale',
                'url_action_secondaire', 'texte_action_secondaire'
            ),
            'classes': ('collapse',)
        }),
        ('Références hiérarchiques', {
            'fields': ('proposition_liee', 'validation_liee'),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': (
                'created_at', 'date_lecture', 'date_traitement',
                'date_expiration', 'prochaine_date_rappel'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('nb_rappels_envoyes', 'metadata'),
            'classes': ('collapse',)
        })
    )

@admin.register(HistoriqueAction)
class HistoriqueActionAdmin(ReadOnlyModelAdmin):
    list_display = (
        'demande', 'display_action_hierarchique', 'display_utilisateur_niveau', 
        'created_at', 'display_details'
    )
    list_filter = ('action', 'niveau_hierarchique', 'is_superuser', 'created_at', 'niveau_validation')
    search_fields = ('demande__numero_demande', 'utilisateur__matricule', 'description')
    readonly_fields = ('created_at',)
    
    fieldsets = (
        ('Action hiérarchique', {
            'fields': ('demande', 'action', 'utilisateur', 'description')
        }),
        ('Références', {
            'fields': ('proposition', 'validation'),
            'classes': ('collapse',)
        }),
        ('Niveau hiérarchique CORRIGÉ', {
            'fields': ('niveau_hierarchique', 'is_superuser', 'niveau_validation'),
            'description': 'Suivi des actions selon la hiérarchie : RESPONSABLE → DIRECTEUR → RH/ADMIN'
        }),
        ('Données', {
            'fields': ('donnees_avant', 'donnees_apres'),
            'classes': ('collapse',)
        }),
        ('Métadonnées techniques', {
            'fields': ('adresse_ip', 'user_agent', 'created_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_action_hierarchique(self, obj):
        """Affiche l'action avec icônes selon la hiérarchie CORRIGÉE"""
        actions_display = {
            'CREATION_DEMANDE': '📝 Création demande',
            'MODIFICATION_DEMANDE': '✏️ Modification demande',
            'PROPOSITION_CANDIDAT': '👤 Proposition candidat',
            'EVALUATION_CANDIDAT': '  Évaluation candidat',
            'VALIDATION_RESPONSABLE': '👔 Validation RESPONSABLE (N+1)',    #   Niveau 1
            'VALIDATION_DIRECTEUR': '🏢 Validation DIRECTEUR (N+2)',        #   Niveau 2
            'VALIDATION_RH': '👨‍💼 Validation RH (Final)',                  #   Niveau 3
            'VALIDATION_ADMIN': '⚙️ Validation ADMIN (Final)',              #   Niveau 3 étendu
            'VALIDATION_SUPERUSER': '  Validation SUPERUSER',           #   Tous niveaux
            'SELECTION_CANDIDAT': '🎯 Sélection candidat',
            'NOTIFICATION_CANDIDAT': '📧 Notification candidat',
            'REPONSE_CANDIDAT': '💬 Réponse candidat',
            'DEBUT_MISSION': '  Début mission',
            'FIN_MISSION': '🏁 Fin mission',
            'ANNULATION': '🚫 Annulation',
            'COMMENTAIRE': '💬 Commentaire',
        }
        return format_html(actions_display.get(obj.action, '❓ Action inconnue'))
    display_action_hierarchique.short_description = "Action"
    
    def display_utilisateur_niveau(self, obj):
        """Affiche l'utilisateur avec son niveau hiérarchique"""
        if obj.utilisateur:
            if obj.is_superuser:
                return format_html('<strong style="color: purple;">  {} (SUPERUSER)</strong>', obj.utilisateur.nom_complet)
            elif obj.niveau_hierarchique:
                niveaux = {
                    'RESPONSABLE': ('👔', 'green'),  #   Niveau 1
                    'DIRECTEUR': ('🏢', 'orange'),   #   Niveau 2
                    'RH': ('👨‍💼', 'red'),             #   Niveau 3
                    'ADMIN': ('⚙️', 'purple'),       #   Niveau 3 étendu
                }
                icon, couleur = niveaux.get(obj.niveau_hierarchique, ('👤', 'gray'))
                return format_html(
                    '<strong style="color: {};">{} {} ({})</strong>',
                    couleur, icon, obj.utilisateur.nom_complet, obj.niveau_hierarchique
                )
            else:
                return format_html('<strong>👤 {}</strong>', obj.utilisateur.nom_complet)
        return "❌ Utilisateur non défini"
    display_utilisateur_niveau.short_description = "Utilisateur (niveau)"
    
    def display_details(self, obj):
        if obj.proposition:
            return format_html('<span style="color: blue;">👤 Proposition</span>')
        elif obj.validation:
            return format_html('<span style="color: purple;">⚖️ Validation</span>')
        else:
            return format_html('<span style="color: gray;">📝 Général</span>')
    display_details.short_description = "Type"

# ================================================================
# ADMIN RÉPONSES CANDIDATS
# ================================================================

@admin.register(ReponseCandidatInterim)
class ReponseCandidatInterimAdmin(BaseModelAdmin):
    list_display = (
        'candidat', 'demande', 'reponse_display', 'display_temps_restant',
        'date_proposition', 'date_reponse'
    )
    list_filter = ('reponse', 'motif_refus', 'date_proposition')
    search_fields = ('candidat__matricule', 'demande__numero_demande')
    readonly_fields = ('date_proposition', 'temps_restant_display', 'est_expire')
    
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
            'fields': ('temps_restant_display', 'est_expire'),
            'classes': ('collapse',)
        })
    )
    
    def display_temps_restant(self, obj):
        return obj.temps_restant_display
    display_temps_restant.short_description = "Temps restant"

# ================================================================
# ADMIN DONNÉES COMPLÉMENTAIRES
# ================================================================

@admin.register(FormationUtilisateur)
class FormationUtilisateurAdmin(BaseModelAdmin):
    list_display = ('utilisateur', 'titre', 'organisme', 'display_periode', 'display_statut')
    list_filter = ('certifiante', 'diplome_obtenu', 'source_donnee', 'type_formation')
    search_fields = ('utilisateur__matricule', 'titre', 'organisme', 'type_formation')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Formation', {
            'fields': ('utilisateur', 'titre', 'description', 'type_formation', 'organisme')
        }),
        ('Période', {
            'fields': (('date_debut', 'date_fin'), 'duree_jours')
        }),
        ('Certification', {
            'fields': ('certifiante', 'diplome_obtenu')
        }),
        ('Kelio', {
            'fields': ('kelio_formation_key', 'source_donnee'),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_periode(self, obj):
        if obj.date_debut and obj.date_fin:
            return f"{obj.date_debut.strftime('%d/%m/%Y')} - {obj.date_fin.strftime('%d/%m/%Y')}"
        elif obj.date_debut:
            return f"Depuis {obj.date_debut.strftime('%d/%m/%Y')}"
        return "Non définie"
    display_periode.short_description = "Période"
    
    def display_statut(self, obj):
        statuts = []
        if obj.certifiante:
            statuts.append("🏆 Certifiante")
        if obj.diplome_obtenu:
            statuts.append("  Obtenu")
        else:
            statuts.append("❌ Non obtenu")
        return " | ".join(statuts)
    display_statut.short_description = "Statut"

@admin.register(AbsenceUtilisateur)
class AbsenceUtilisateurAdmin(ReadOnlyModelAdmin):
    list_display = ('utilisateur', 'type_absence', 'display_periode', 'display_duree', 'display_statut')
    list_filter = ('type_absence', 'source_donnee', 'date_debut')
    search_fields = ('utilisateur__matricule', 'type_absence', 'commentaire')
    readonly_fields = ('created_at', 'updated_at', 'est_en_cours')
    ordering = ('-date_debut',)
    
    fieldsets = (
        ('Absence', {
            'fields': ('utilisateur', 'type_absence', 'commentaire')
        }),
        ('Période', {
            'fields': (('date_debut', 'date_fin'), 'duree_jours')
        }),
        ('Kelio', {
            'fields': ('kelio_absence_file_key', 'source_donnee'),
            'classes': ('collapse',)
        }),
        ('Statut', {
            'fields': ('est_en_cours',),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_periode(self, obj):
        return f"{obj.date_debut.strftime('%d/%m/%Y')} - {obj.date_fin.strftime('%d/%m/%Y')}"
    display_periode.short_description = "Période"
    
    def display_duree(self, obj):
        return f"{obj.duree_jours} jour{'s' if obj.duree_jours > 1 else ''}"
    display_duree.short_description = "Durée"
    
    def display_statut(self, obj):
        if obj.est_en_cours:
            return format_html('<span style="color: orange;">🟡 En cours</span>')
        else:
            return format_html('<span style="color: gray;">⚫ Terminée</span>')
    display_statut.short_description = "Statut"

@admin.register(DisponibiliteUtilisateur)
class DisponibiliteUtilisateurAdmin(BaseModelAdmin):
    list_display = ('utilisateur', 'type_disponibilite', 'display_periode', 'created_by', 'created_at')
    list_filter = ('type_disponibilite', 'date_debut')
    search_fields = ('utilisateur__matricule', 'commentaire')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Disponibilité', {
            'fields': ('utilisateur', 'type_disponibilite', 'commentaire')
        }),
        ('Période', {
            'fields': (('date_debut', 'date_fin'),)
        }),
        ('Suivi', {
            'fields': ('created_by',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_periode(self, obj):
        return f"{obj.date_debut.strftime('%d/%m/%Y')} - {obj.date_fin.strftime('%d/%m/%Y')}"
    display_periode.short_description = "Période"

# ================================================================
# ADMINS POUR LES MODÈLES ÉTENDUS
# ================================================================

@admin.register(ProfilUtilisateurKelio)
class ProfilUtilisateurKelioAdmin(BaseModelAdmin):
    list_display = ('profil', 'kelio_employee_key', 'kelio_badge_code', 'temps_travail_kelio', 'updated_at')
    list_filter = ('temps_travail_kelio', 'horaires_specifiques_autorises')
    search_fields = ('profil__matricule', 'kelio_badge_code', 'code_personnel')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Liaison', {
            'fields': ('profil', 'kelio_employee_key', 'kelio_badge_code')
        }),
        ('Informations Kelio', {
            'fields': (
                ('telephone_kelio', 'email_kelio'),
                ('date_embauche_kelio', 'type_contrat_kelio'),
                'temps_travail_kelio'
            )
        }),
        ('Configuration', {
            'fields': (
                'code_personnel', 'profil_acces',
                'horaires_specifiques_autorises'
            )
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

@admin.register(ProfilUtilisateurExtended)
class ProfilUtilisateurExtendedAdmin(BaseModelAdmin):
    list_display = (
        'profil', 'display_disponible_interim', 'display_contact', 
        'display_contrat', 'rayon_deplacement_km', 'updated_at'
    )
    list_filter = ('disponible_interim', 'type_contrat', 'situation_handicap')
    search_fields = ('profil__matricule', 'telephone', 'telephone_portable')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Profil étendu', {
            'fields': ('profil', 'disponible_interim', 'rayon_deplacement_km')
        }),
        ('Contact', {
            'fields': ('telephone', 'telephone_portable')
        }),
        ('Emploi', {
            'fields': (
                ('date_embauche', 'date_fin_contrat'),
                ('type_contrat', 'temps_travail'),
                ('coefficient', 'niveau_classification', 'statut_professionnel')
            )
        }),
        ('Médical et légal', {
            'fields': (
                'prochaine_visite_medicale', 'permis_conduire',
                'situation_handicap'
            ),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_disponible_interim(self, obj):
        if obj.disponible_interim:
            return format_html('<span style="color: green;">  Disponible</span>')
        else:
            return format_html('<span style="color: red;">❌ Non disponible</span>')
    display_disponible_interim.short_description = "Intérim"
    
    def display_contact(self, obj):
        contact = []
        if obj.telephone:
            contact.append(f"📞 {obj.telephone}")
        if obj.telephone_portable:
            contact.append(f"📱 {obj.telephone_portable}")
        return " | ".join(contact) if contact else "Aucun"
    display_contact.short_description = "Contact"
    
    def display_contrat(self, obj):
        infos = []
        if obj.type_contrat:
            infos.append(obj.type_contrat)
        if obj.temps_travail:
            infos.append(f"{obj.temps_travail*100:.0f}%")
        return " | ".join(infos) if infos else "N/A"
    display_contrat.short_description = "Contrat"

# ================================================================
# ADMIN POUR LES SCORES DÉTAILLÉS ET WORKFLOW
# ================================================================

@admin.register(ScoreDetailCandidat)
class ScoreDetailCandidatAdmin(ReadOnlyModelAdmin):
    list_display = (
        'candidat', 'demande_interim', 'score_total', 'display_type_candidat',
        'display_proposant', 'display_bonus_hierarchique', 'calcule_par', 'created_at'
    )
    list_filter = ('calcule_par', 'demande_interim__urgence')
    search_fields = ('candidat__matricule', 'demande_interim__numero_demande')
    readonly_fields = ('created_at', 'updated_at', 'est_proposition_humaine', 'proposant_display')
    
    fieldsets = (
        ('Score', {
            'fields': ('candidat', 'demande_interim', 'proposition_humaine', 'score_total', 'calcule_par')
        }),
        ('Scores détaillés', {
            'fields': (
                ('score_similarite_poste', 'score_competences'),
                ('score_experience', 'score_disponibilite'),
                ('score_proximite', 'score_anciennete')
            )
        }),
        ('Bonus et pénalités avec hiérarchie CORRIGÉE', {
            'fields': (
                ('bonus_proposition_humaine', 'bonus_experience_similaire'),
                'bonus_recommandation', 'bonus_hierarchique',  #   Nouveau champ
                'penalite_indisponibilite'
            ),
            'description': 'Bonus hiérarchique : RESPONSABLE (+15) → DIRECTEUR (+18) → RH/ADMIN (+20)'
        }),
        ('Métadonnées', {
            'fields': ('est_proposition_humaine', 'proposant_display', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_type_candidat(self, obj):
        if obj.est_proposition_humaine:
            return format_html('<span style="color: blue;">👤 Proposition humaine</span>')
        else:
            return format_html('<span style="color: green;">🤖 Sélection automatique</span>')
    display_type_candidat.short_description = "Type"
    
    def display_proposant(self, obj):
        return obj.proposant_display
    display_proposant.short_description = "Proposant"
    
    def display_bonus_hierarchique(self, obj):
        """Affiche le bonus hiérarchique"""
        if obj.bonus_hierarchique > 0:
            return format_html('<span style="color: green; font-weight: bold;">+{} points</span>', obj.bonus_hierarchique)
        else:
            return format_html('<span style="color: gray;">Aucun</span>')
    display_bonus_hierarchique.short_description = "Bonus hiérarchique"

@admin.register(WorkflowDemande)
class WorkflowDemandeAdmin(ReadOnlyModelAdmin):
    list_display = (
        'demande', 'etape_actuelle', 'display_progression', 'display_retard',
        'nb_propositions_recues', 'date_derniere_action'
    )
    list_filter = ('etape_actuelle', 'created_at')
    search_fields = ('demande__numero_demande',)
    readonly_fields = (
        'created_at', 'updated_at', 'progression_percentage', 'est_en_retard',
        'date_derniere_action'
    )
    
    fieldsets = (
        ('Workflow', {
            'fields': ('demande', 'etape_actuelle', 'date_derniere_action')
        }),
        ('Progression', {
            'fields': ('progression_percentage', 'est_en_retard')
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
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_progression(self, obj):
        progression = obj.progression_percentage
        if progression >= 100:
            return format_html('<span style="color: green; font-weight: bold;">  {:.0f}%</span>', progression)
        elif progression >= 75:
            return format_html('<span style="color: blue; font-weight: bold;">🔵 {:.0f}%</span>', progression)
        elif progression >= 50:
            return format_html('<span style="color: orange; font-weight: bold;">🟡 {:.0f}%</span>', progression)
        else:
            return format_html('<span style="color: red; font-weight: bold;">🔴 {:.0f}%</span>', progression)
    display_progression.short_description = "Progression"
    
    def display_retard(self, obj):
        if obj.est_en_retard:
            return format_html('<span style="color: red; font-weight: bold;">🚨 En retard</span>')
        else:
            return format_html('<span style="color: green;">  Dans les temps</span>')
    display_retard.short_description = "Délais"

# ================================================================
# ADMIN CACHE KELIO
# ================================================================

@admin.register(CacheApiKelio)
class CacheApiKelioAdmin(ReadOnlyModelAdmin):
    list_display = (
        'configuration', 'service_name', 'display_cle_cache', 'nb_acces',
        'display_statut', 'created_at'
    )
    list_filter = ('service_name', 'configuration', 'created_at')
    search_fields = ('cle_cache', 'service_name')
    readonly_fields = ('created_at', 'updated_at', 'est_expire', 'taille_donnees')
    
    fieldsets = (
        ('Cache', {
            'fields': ('configuration', 'service_name', 'cle_cache')
        }),
        ('Données', {
            'fields': ('parametres_requete', 'donnees', 'taille_donnees')
        }),
        ('Utilisation', {
            'fields': ('nb_acces', 'date_expiration', 'est_expire')
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def display_cle_cache(self, obj):
        cle = obj.cle_cache
        if len(cle) > 50:
            return f"{cle[:47]}..."
        return cle
    display_cle_cache.short_description = "Clé cache"
    
    def display_statut(self, obj):
        if obj.est_expire:
            return format_html('<span style="color: red;">❌ Expiré</span>')
        else:
            return format_html('<span style="color: green;">  Valide</span>')
    display_statut.short_description = "Statut"

# ================================================================
# VUES PERSONNALISÉES POUR GESTION DES MOTS DE PASSE
# ================================================================

@staff_member_required
def change_password_view(request, user_id):
    """Vue pour changer le mot de passe d'un utilisateur spécifique"""
    user = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        form = AdminPasswordChangeForm(user, request.POST)
        if form.is_valid():
            form.save()
            
            # Maintenir la session si l'utilisateur change son propre mot de passe
            if user == request.user:
                update_session_auth_hash(request, user)
            
            messages.success(request, f'Mot de passe de {user.username} modifié avec succès.')
            return redirect('admin:auth_user_changelist')
    else:
        form = AdminPasswordChangeForm(user)
    
    context = {
        'title': f'Changer le mot de passe de {user.username}',
        'form': form,
        'user_obj': user,
        'opts': User._meta,
        'has_permission': True,
    }
    
    return TemplateResponse(request, 'admin/auth/user/change_password.html', context)

@staff_member_required
def reset_multiple_passwords_view(request, user_ids):
    """Vue pour réinitialiser plusieurs mots de passe"""
    try:
        user_id_list = [int(id) for id in user_ids.split(',')]
        users = User.objects.filter(id__in=user_id_list)
        
        if request.method == 'POST':
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')
            
            if not new_password:
                messages.error(request, "Le nouveau mot de passe est requis.")
            elif new_password != confirm_password:
                messages.error(request, "Les mots de passe ne correspondent pas.")
            elif len(new_password) < 8:
                messages.error(request, "Le mot de passe doit contenir au moins 8 caractères.")
            else:
                # Réinitialiser les mots de passe
                updated_count = 0
                for user in users:
                    user.set_password(new_password)
                    user.save()
                    updated_count += 1
                
                messages.success(request, f'Mots de passe réinitialisés pour {updated_count} utilisateur(s).')
                return redirect('admin:auth_user_changelist')
        
        context = {
            'title': 'Réinitialisation de mots de passe',
            'users': users,
            'user_count': users.count(),
            'opts': User._meta,
            'has_permission': True,
        }
        
        return TemplateResponse(request, 'admin/auth/user/reset_multiple_passwords.html', context)
        
    except (ValueError, TypeError):
        messages.error(request, "IDs d'utilisateurs invalides.")
        return redirect('admin:auth_user_changelist')

@staff_member_required
def generate_temp_password_view(request, user_id):
    """Vue pour générer un mot de passe temporaire"""
    user = get_object_or_404(User, pk=user_id)
    
    if request.method == 'POST':
        # Générer un mot de passe temporaire
        import secrets
        import string
        
        alphabet = string.ascii_letters + string.digits
        temp_password = ''.join(secrets.choice(alphabet) for _ in range(12))
        
        # Définir le mot de passe temporaire
        user.set_password(temp_password)
        user.save()
        
        # Afficher le mot de passe temporaire (une seule fois)
        context = {
            'title': f'Mot de passe temporaire pour {user.username}',
            'user_obj': user,
            'temp_password': temp_password,
            'opts': User._meta,
            'has_permission': True,
        }
        
        return TemplateResponse(request, 'admin/auth/user/temp_password_generated.html', context)
    
    context = {
        'title': f'Générer un mot de passe temporaire pour {user.username}',
        'user_obj': user,
        'opts': User._meta,
        'has_permission': True,
    }
    
    return TemplateResponse(request, 'admin/auth/user/generate_temp_password.html', context)

# ================================================================
# URLS PERSONNALISÉES POUR GESTION DES MOTS DE PASSE
# ================================================================

def get_admin_urls_password_management():
    """URLs personnalisées pour la gestion des mots de passe"""
    
    return [
        # Gestion des mots de passe
        path('auth/user/<int:user_id>/password/', change_password_view, name='user_change_password'),
        path('auth/user/reset-passwords/<str:user_ids>/', reset_multiple_passwords_view, name='reset_multiple_passwords'),
        path('auth/user/<int:user_id>/temp-password/', generate_temp_password_view, name='generate_temp_password'),
    ]

# ================================================================
# FILTRES PERSONNALISÉS POUR LA HIÉRARCHIE
# ================================================================

class HierarchieFilter(SimpleListFilter):
    """Filtre par niveau hiérarchique"""
    title = 'Niveau hiérarchique'
    parameter_name = 'niveau_hierarchique'
    
    def lookups(self, request, model_admin):
        return [
            ('niveau_1', '👔 Niveau 1 - RESPONSABLE'),
            ('niveau_2', '🏢 Niveau 2 - DIRECTEUR'),
            ('niveau_3', '👨‍💼 Niveau 3 - RH/ADMIN'),
            ('superuser', '  SUPERUTILISATEUR'),
            ('autres', '👤 Autres niveaux'),
        ]
    
    def queryset(self, request, queryset):
        if self.value() == 'niveau_1':
            return queryset.filter(type_profil='RESPONSABLE')
        elif self.value() == 'niveau_2':
            return queryset.filter(type_profil='DIRECTEUR')
        elif self.value() == 'niveau_3':
            return queryset.filter(type_profil__in=['RH', 'ADMIN'])
        elif self.value() == 'superuser':
            return queryset.filter(user__is_superuser=True)
        elif self.value() == 'autres':
            return queryset.filter(type_profil__in=['UTILISATEUR', 'CHEF_EQUIPE'])
        return queryset

class ValidationHierarchiqueFilter(SimpleListFilter):
    """Filtre par type de validation hiérarchique"""
    title = 'Type validation hiérarchique'
    parameter_name = 'type_validation_hierarchique'
    
    def lookups(self, request, model_admin):
        return [
            ('niveau_1', '👔 Niveau 1 - RESPONSABLE'),
            ('niveau_2', '🏢 Niveau 2 - DIRECTEUR'),
            ('niveau_3_rh', '👨‍💼 Niveau 3 - RH'),
            ('niveau_3_admin', '⚙️ Niveau 3 - ADMIN'),
            ('superuser', '  SUPERUTILISATEUR'),
            ('en_attente', '⏳ En attente'),
            ('terminees', '  Terminées'),
        ]
    
    def queryset(self, request, queryset):
        if self.value() == 'niveau_1':
            return queryset.filter(type_validation='RESPONSABLE')
        elif self.value() == 'niveau_2':
            return queryset.filter(type_validation='DIRECTEUR')
        elif self.value() == 'niveau_3_rh':
            return queryset.filter(type_validation='RH')
        elif self.value() == 'niveau_3_admin':
            return queryset.filter(type_validation='ADMIN')
        elif self.value() == 'superuser':
            return queryset.filter(type_validation='SUPERUSER')
        elif self.value() == 'en_attente':
            return queryset.filter(date_validation__isnull=True)
        elif self.value() == 'terminees':
            return queryset.filter(date_validation__isnull=False)
        return queryset

# Ajouter le filtre aux admins appropriés
ProfilUtilisateurAdmin.list_filter = ProfilUtilisateurAdmin.list_filter + (HierarchieFilter,)
ValidationDemandeAdmin.list_filter = ValidationDemandeAdmin.list_filter + (ValidationHierarchiqueFilter,)

# ================================================================
# ACTIONS EN LOT POUR LA HIÉRARCHIE
# ================================================================

@admin.action(description="Promouvoir au niveau RESPONSABLE")
def promouvoir_responsable(modeladmin, request, queryset):
    """Promeut les utilisateurs sélectionnés au niveau RESPONSABLE"""
    updated = queryset.update(type_profil='RESPONSABLE')
    modeladmin.message_user(
        request, 
        f"{updated} utilisateur(s) promu(s) au niveau RESPONSABLE (Niveau 1 de validation)."
    )

@admin.action(description="Promouvoir au niveau DIRECTEUR")
def promouvoir_directeur(modeladmin, request, queryset):
    """Promeut les utilisateurs sélectionnés au niveau DIRECTEUR"""
    updated = queryset.update(type_profil='DIRECTEUR')
    modeladmin.message_user(
        request, 
        f"{updated} utilisateur(s) promu(s) au niveau DIRECTEUR (Niveau 2 de validation)."
    )

@admin.action(description="Promouvoir au niveau RH")
def promouvoir_rh(modeladmin, request, queryset):
    """Promeut les utilisateurs sélectionnés au niveau RH"""
    updated = queryset.update(type_profil='RH')
    modeladmin.message_user(
        request, 
        f"{updated} utilisateur(s) promu(s) au niveau RH (Niveau 3 - validation finale)."
    )

@admin.action(description="Promouvoir au niveau ADMIN")
def promouvoir_admin(modeladmin, request, queryset):
    """Promeut les utilisateurs sélectionnés au niveau ADMIN"""
    updated = queryset.update(type_profil='ADMIN')
    modeladmin.message_user(
        request, 
        f"{updated} utilisateur(s) promu(s) au niveau ADMIN (Niveau 3 étendu - validation finale)."
    )

@admin.action(description="Rétrograder en UTILISATEUR")
def retrograder_utilisateur(modeladmin, request, queryset):
    """Rétrograde les utilisateurs sélectionnés au niveau UTILISATEUR"""
    updated = queryset.update(type_profil='UTILISATEUR')
    modeladmin.message_user(
        request, 
        f"{updated} utilisateur(s) rétrogradé(s) au niveau UTILISATEUR (aucun droit de validation)."
    )

# ================================================================
# ACTIONS PERSONNALISÉES POUR LA SYNCHRONISATION
# ================================================================

@admin.action(description="🔄 Synchroniser avec User Django")
def synchroniser_avec_user(modeladmin, request, queryset):
    """Synchronise les profils avec leurs utilisateurs Django"""
    synchronized = 0
    errors = 0
    
    for profil in queryset:
        try:
            if profil.sync_with_user():
                synchronized += 1
            else:
                errors += 1
        except Exception:
            errors += 1
    
    if synchronized > 0:
        modeladmin.message_user(request, f"  {synchronized} profil(s) synchronisé(s)")
    if errors > 0:
        modeladmin.message_user(request, f"❌ {errors} erreur(s) de synchronisation", level=messages.ERROR)

@admin.action(description="🔐 Réinitialiser mots de passe")
def reinitialiser_mots_de_passe_profils(modeladmin, request, queryset):
    """Réinitialise les mots de passe pour les profils sélectionnés"""
    if queryset.count() > 5:
        modeladmin.message_user(request, "❌ Maximum 5 profils à la fois", level=messages.ERROR)
        return
    
    import secrets
    import string
    
    for profil in queryset:
        if profil.user:
            # Générer un mot de passe temporaire
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            
            if profil.set_user_password(temp_password):
                modeladmin.message_user(
                    request, 
                    f"🔐 Mot de passe réinitialisé pour {profil.nom_complet}: {temp_password}"
                )
            else:
                modeladmin.message_user(
                    request,
                    f"❌ Erreur réinitialisation pour {profil.nom_complet}",
                    level=messages.ERROR
                )

# Ajouter les actions à ProfilUtilisateurAdmin
ProfilUtilisateurAdmin.actions = ProfilUtilisateurAdmin.actions + [
    promouvoir_responsable,
    promouvoir_directeur, 
    promouvoir_rh,
    promouvoir_admin,
    retrograder_utilisateur,
    synchroniser_avec_user,
    reinitialiser_mots_de_passe_profils    
]

# ================================================================
# CONFIGURATION FINALE ET ENREGISTREMENT
# ================================================================

# Personnaliser le site admin par défaut
admin.site.site_header = "Administration Intérim - Hiérarchie CORRIGÉE - Kelio SANS cryptage"
admin.site.site_title = "Intérim Admin"
admin.site.index_title = "Tableau de bord - RESPONSABLE → DIRECTEUR → RH/ADMIN"

# Configuration avancée
admin.site.empty_value_display = "❌ Non renseigné"

# Configuration des URLs personnalisées
class InterimAdminSite(admin.AdminSite):
    """Site d'administration avec URLs personnalisées"""
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = get_admin_urls_password_management()
        return custom_urls + urls

'''
# Log de confirmation du chargement
logger.info("  Interface d'administration SANS CRYPTAGE chargée")
logger.info("  Adaptations réalisées :")
logger.info("   •   Hiérarchie : RESPONSABLE (N+1) → DIRECTEUR (N+2) → RH/ADMIN (Final)")
logger.info("   •   Superutilisateurs : Droits complets à tous niveaux")
logger.info("   •   Configuration Kelio : Mot de passe stocké en CLAIR")
logger.info("   •   Bonus hiérarchiques dans le scoring")
logger.info("   •   Filtres par niveau hiérarchique")
logger.info("   •   Actions de promotion/rétrogradation")
logger.info("   •   Affichage adapté dans tous les admins")
logger.info("   •   Gestion complète des mots de passe maintenue")
logger.info("   •   Propositions de candidats intégrées")
logger.info("  Système d'administration SANS cryptage opérationnel !")

print("  admin.py RÉÉCRIT - Configuration Kelio SANS cryptage !")
print("  Niveaux : RESPONSABLE (N+1) → DIRECTEUR (N+2) → RH/ADMIN (Final)")
print("  Superutilisateurs : Droits complets automatiques")
print("  Bonus hiérarchiques configurés dans le scoring")
print("  Gestion des mots de passe sécurisée maintenue")
print("  Propositions de candidats avec hiérarchie intégrées")
print("  Configuration Kelio : Mot de passe stocké en CLAIR (non crypté)")

'''

# ================================================================
# ADMINISTRATION DES JOURS FÉRIÉS
# À ajouter à la fin de votre fichier admin.py existant
# ================================================================

from .models import (
    ModeleJourFerie, JourFerie, HistoriqueModification,
    TypeJourFerie, MethodeCalcul, StatutJourFerie
)

# ================================================================
# FILTRES PERSONNALISÉS POUR JOURS FÉRIÉS
# ================================================================

class AnneeJourFerieFilter(SimpleListFilter):
    """Filtre par année"""
    title = 'Année'
    parameter_name = 'annee'
    
    def lookups(self, request, model_admin):
        annees = JourFerie.objects.values_list('annee', flat=True).distinct().order_by('-annee')
        return [(str(a), str(a)) for a in annees]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(annee=int(self.value()))
        return queryset


class TypeFerieFilter(SimpleListFilter):
    """Filtre par type de jour férié"""
    title = 'Type de férié'
    parameter_name = 'type_ferie'
    
    def lookups(self, request, model_admin):
        return [
            ('FERIE_CIVIL', '🏛️ Civil'),
            ('FERIE_CHRETIEN', '✝️ Chrétien'),
            ('FERIE_MUSULMAN', '☪️ Musulman'),
            ('FERIE_INTERNE', '🏢 Interne'),
            ('FERIE_AUTRE', '📅 Autre'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(type_ferie=self.value())
        return queryset


class StatutFerieFilter(SimpleListFilter):
    """Filtre par statut"""
    title = 'Statut'
    parameter_name = 'statut'
    
    def lookups(self, request, model_admin):
        return [
            ('ACTIF', '✅ Actif'),
            ('INACTIF', '❌ Inactif'),
            ('EN_ATTENTE', '⏳ En attente'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(statut=self.value())
        return queryset


class MethodeCalculFilter(SimpleListFilter):
    """Filtre par méthode de calcul"""
    title = 'Méthode de calcul'
    parameter_name = 'methode_calcul'
    
    def lookups(self, request, model_admin):
        return [
            ('FIXE', '📆 Date fixe'),
            ('PAQUES', '🐣 Basé sur Pâques'),
            ('HIJRI', '🌙 Calendrier Hijri'),
            ('MANUEL', '✏️ Manuel'),
        ]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(methode_calcul=self.value())
        return queryset


# ================================================================
# INLINE POUR L'HISTORIQUE DES MODIFICATIONS
# ================================================================

class HistoriqueModificationInline(admin.TabularInline):
    """Inline pour afficher l'historique des modifications"""
    model = HistoriqueModification
    extra = 0
    readonly_fields = ['action', 'champ_modifie', 'ancienne_valeur', 'nouvelle_valeur', 'motif', 'effectue_par', 'date_action']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


# ================================================================
# ADMIN: ModeleJourFerie
# ================================================================

@admin.register(ModeleJourFerie)
class ModeleJourFerieAdmin(admin.ModelAdmin):
    """Administration des modèles/templates de jours fériés"""
    
    list_display = [
        'nom', 'code', 'badge_type_ferie', 'badge_methode_calcul',
        'afficher_date_reference', 'badge_modifiable', 'badge_actif'
    ]
    list_filter = [TypeFerieFilter, MethodeCalculFilter, 'est_actif', 'est_systeme', 'code_pays']
    search_fields = ['nom', 'code', 'description']
    ordering = ['mois_fixe', 'jour_fixe', 'nom']
    
    fieldsets = (
        ('Identification', {
            'fields': ('code', 'nom', 'description')
        }),
        ('Classification', {
            'fields': ('type_ferie', 'methode_calcul', 'code_pays')
        }),
        ('Date fixe', {
            'fields': ('mois_fixe', 'jour_fixe'),
            'classes': ('collapse',),
            'description': 'Pour les jours fériés à date fixe (ex: 1er janvier, 25 décembre)'
        }),
        ('Basé sur Pâques', {
            'fields': ('decalage_paques',),
            'classes': ('collapse',),
            'description': 'Nombre de jours après Pâques (ex: 1 pour Lundi de Pâques)'
        }),
        ('Calendrier Hijri', {
            'fields': ('mois_hijri', 'jour_hijri'),
            'classes': ('collapse',),
            'description': 'Pour les fêtes islamiques (calendrier lunaire)'
        }),
        ('Configuration', {
            'fields': ('est_national', 'est_paye', 'est_modifiable', 'est_systeme', 'est_actif')
        }),
    )
    
    readonly_fields = ['date_creation', 'date_modification']
    
    actions = ['activer_modeles', 'desactiver_modeles', 'generer_annee_courante']
    
    # Badges colorés
    @admin.display(description='Type')
    def badge_type_ferie(self, obj):
        colors = {
            'FERIE_CIVIL': '#3498db',
            'FERIE_CHRETIEN': '#9b59b6',
            'FERIE_MUSULMAN': '#27ae60',
            'FERIE_INTERNE': '#e67e22',
            'FERIE_AUTRE': '#95a5a6',
        }
        icons = {
            'FERIE_CIVIL': '🏛️',
            'FERIE_CHRETIEN': '✝️',
            'FERIE_MUSULMAN': '☪️',
            'FERIE_INTERNE': '🏢',
            'FERIE_AUTRE': '📅',
        }
        color = colors.get(obj.type_ferie, '#95a5a6')
        icon = icons.get(obj.type_ferie, '📅')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; border-radius:4px;">{} {}</span>',
            color, icon, obj.get_type_ferie_display()
        )
    
    @admin.display(description='Méthode')
    def badge_methode_calcul(self, obj):
        colors = {
            'FIXE': '#2ecc71',
            'PAQUES': '#f39c12',
            'HIJRI': '#1abc9c',
            'MANUEL': '#e74c3c',
        }
        icons = {
            'FIXE': '📆',
            'PAQUES': '🐣',
            'HIJRI': '🌙',
            'MANUEL': '✏️',
        }
        color = colors.get(obj.methode_calcul, '#95a5a6')
        icon = icons.get(obj.methode_calcul, '📅')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; border-radius:4px;">{} {}</span>',
            color, icon, obj.get_methode_calcul_display()
        )
    
    @admin.display(description='Date référence')
    def afficher_date_reference(self, obj):
        if obj.methode_calcul == 'FIXE' and obj.mois_fixe and obj.jour_fixe:
            return f"{obj.jour_fixe:02d}/{obj.mois_fixe:02d}"
        elif obj.methode_calcul == 'PAQUES' and obj.decalage_paques is not None:
            if obj.decalage_paques == 0:
                return "Pâques"
            elif obj.decalage_paques > 0:
                return f"Pâques +{obj.decalage_paques}j"
            else:
                return f"Pâques {obj.decalage_paques}j"
        elif obj.methode_calcul == 'HIJRI' and obj.mois_hijri and obj.jour_hijri:
            return f"{obj.jour_hijri}/{obj.mois_hijri} (Hijri)"
        return "-"
    
    @admin.display(description='Modifiable', boolean=True)
    def badge_modifiable(self, obj):
        return obj.est_modifiable
    
    @admin.display(description='Actif', boolean=True)
    def badge_actif(self, obj):
        return obj.est_actif
    
    # Actions
    @admin.action(description="✅ Activer les modèles sélectionnés")
    def activer_modeles(self, request, queryset):
        updated = queryset.update(est_actif=True)
        self.message_user(request, f"✅ {updated} modèle(s) activé(s)")
    
    @admin.action(description="❌ Désactiver les modèles sélectionnés")
    def desactiver_modeles(self, request, queryset):
        updated = queryset.update(est_actif=False)
        self.message_user(request, f"❌ {updated} modèle(s) désactivé(s)")
    
    @admin.action(description="📅 Générer les jours fériés de l'année courante")
    def generer_annee_courante(self, request, queryset):
        from datetime import date
        annee = date.today().year
        resultats = JourFerie.objects.generer_annee(annee, utilisateur=request.user.username)
        nb_crees = len(resultats.get('crees', []))
        nb_ignores = len(resultats.get('ignores', []))
        
        if nb_crees > 0:
            self.message_user(request, f"✅ {nb_crees} jour(s) férié(s) créé(s) pour {annee}")
        else:
            self.message_user(request, f"ℹ️ Tous les jours fériés {annee} existent déjà ({nb_ignores} ignoré(s))")


# ================================================================
# ADMIN: JourFerie
# ================================================================

@admin.register(JourFerie)
class JourFerieAdmin(admin.ModelAdmin):
    """Administration des instances de jours fériés"""
    
    list_display = [
        'nom', 'afficher_date', 'afficher_jour_semaine', 'annee',
        'badge_type_ferie', 'badge_statut', 'badge_modifie', 'badge_personnalise'
    ]
    list_filter = [AnneeJourFerieFilter, TypeFerieFilter, StatutFerieFilter, 'est_personnalise', 'est_modifie', 'code_pays']
    search_fields = ['nom', 'description', 'modele__code']
    ordering = ['-annee', 'date_ferie']
    date_hierarchy = 'date_ferie'
    
    fieldsets = (
        ('Identification', {
            'fields': ('modele', 'nom', 'description', 'annee')
        }),
        ('Dates', {
            'fields': ('date_ferie', 'date_calculee')
        }),
        ('Classification', {
            'fields': ('type_ferie', 'statut', 'code_pays')
        }),
        ('Caractéristiques', {
            'fields': ('est_national', 'est_paye', 'est_modifie', 'est_personnalise')
        }),
        ('Traçabilité', {
            'fields': ('cree_par', 'modifie_par', 'date_creation', 'date_modification'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['date_calculee', 'date_creation', 'date_modification', 'est_modifie']
    inlines = [HistoriqueModificationInline]
    
    actions = [
        'activer_feries', 'desactiver_feries', 'reinitialiser_dates',
        'generer_annee_2025', 'generer_annee_2026', 'generer_annee_suivante'
    ]
    
    # Affichages personnalisés
    @admin.display(description='Date')
    def afficher_date(self, obj):
        return obj.date_ferie.strftime('%d/%m/%Y')
    
    @admin.display(description='Jour')
    def afficher_jour_semaine(self, obj):
        jours = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
        jour = jours[obj.date_ferie.weekday()]
        if obj.date_ferie.weekday() >= 5:  # Weekend
            return format_html('<span style="color:#e74c3c; font-weight:bold;">{}</span>', jour)
        return jour
    
    @admin.display(description='Type')
    def badge_type_ferie(self, obj):
        colors = {
            'FERIE_CIVIL': '#3498db',
            'FERIE_CHRETIEN': '#9b59b6',
            'FERIE_MUSULMAN': '#27ae60',
            'FERIE_INTERNE': '#e67e22',
            'FERIE_AUTRE': '#95a5a6',
        }
        icons = {
            'FERIE_CIVIL': '🏛️',
            'FERIE_CHRETIEN': '✝️',
            'FERIE_MUSULMAN': '☪️',
            'FERIE_INTERNE': '🏢',
            'FERIE_AUTRE': '📅',
        }
        color = colors.get(obj.type_ferie, '#95a5a6')
        icon = icons.get(obj.type_ferie, '📅')
        return format_html(
            '<span style="background:{}; color:white; padding:2px 6px; border-radius:3px; font-size:11px;">{}</span>',
            color, icon
        )
    
    @admin.display(description='Statut')
    def badge_statut(self, obj):
        colors = {
            'ACTIF': '#27ae60',
            'INACTIF': '#e74c3c',
            'EN_ATTENTE': '#f39c12',
        }
        icons = {
            'ACTIF': '✅',
            'INACTIF': '❌',
            'EN_ATTENTE': '⏳',
        }
        color = colors.get(obj.statut, '#95a5a6')
        icon = icons.get(obj.statut, '❓')
        return format_html(
            '<span style="background:{}; color:white; padding:2px 6px; border-radius:3px; font-size:11px;">{} {}</span>',
            color, icon, obj.get_statut_display()
        )
    
    @admin.display(description='Modifié', boolean=True)
    def badge_modifie(self, obj):
        return obj.est_modifie
    
    @admin.display(description='Perso', boolean=True)
    def badge_personnalise(self, obj):
        return obj.est_personnalise
    
    # Actions
    @admin.action(description="✅ Activer les jours fériés sélectionnés")
    def activer_feries(self, request, queryset):
        for ferie in queryset:
            ferie.reactiver(utilisateur=request.user.username)
        self.message_user(request, f"✅ {queryset.count()} jour(s) férié(s) activé(s)")
    
    @admin.action(description="❌ Désactiver les jours fériés sélectionnés")
    def desactiver_feries(self, request, queryset):
        for ferie in queryset:
            ferie.desactiver(motif="Désactivé via admin", utilisateur=request.user.username)
        self.message_user(request, f"❌ {queryset.count()} jour(s) férié(s) désactivé(s)")
    
    @admin.action(description="🔄 Réinitialiser les dates aux valeurs calculées")
    def reinitialiser_dates(self, request, queryset):
        count = 0
        for ferie in queryset.filter(est_modifie=True):
            try:
                ferie.reinitialiser_date(utilisateur=request.user.username)
                count += 1
            except Exception:
                pass
        self.message_user(request, f"🔄 {count} date(s) réinitialisée(s)")
    
    @admin.action(description="📅 Générer les jours fériés 2025")
    def generer_annee_2025(self, request, queryset):
        self._generer_annee(request, 2025)
    
    @admin.action(description="📅 Générer les jours fériés 2026")
    def generer_annee_2026(self, request, queryset):
        self._generer_annee(request, 2026)
    
    @admin.action(description="📅 Générer les jours fériés de l'année suivante")
    def generer_annee_suivante(self, request, queryset):
        from datetime import date
        annee = date.today().year + 1
        self._generer_annee(request, annee)
    
    def _generer_annee(self, request, annee):
        """Méthode utilitaire pour générer une année"""
        # S'assurer que les modèles existent
        ModeleJourFerie.objects.charger_donnees_initiales()
        
        resultats = JourFerie.objects.generer_annee(annee, utilisateur=request.user.username)
        nb_crees = len(resultats.get('crees', []))
        nb_ignores = len(resultats.get('ignores', []))
        nb_erreurs = len(resultats.get('erreurs', []))
        
        if nb_crees > 0:
            self.message_user(request, f"✅ {nb_crees} jour(s) férié(s) créé(s) pour {annee}")
        elif nb_ignores > 0:
            self.message_user(request, f"ℹ️ Tous les jours fériés {annee} existent déjà")
        
        if nb_erreurs > 0:
            self.message_user(request, f"⚠️ {nb_erreurs} erreur(s) lors de la génération", level=messages.WARNING)


# ================================================================
# ADMIN: HistoriqueModification
# ================================================================

@admin.register(HistoriqueModification)
class HistoriqueModificationAdmin(admin.ModelAdmin):
    """Administration de l'historique des modifications"""
    
    list_display = [
        'jour_ferie', 'badge_action', 'champ_modifie',
        'ancienne_valeur_courte', 'nouvelle_valeur_courte',
        'effectue_par', 'date_action'
    ]
    list_filter = ['action', 'champ_modifie', 'effectue_par']
    search_fields = ['jour_ferie__nom', 'motif', 'effectue_par']
    ordering = ['-date_action']
    date_hierarchy = 'date_action'
    
    readonly_fields = [
        'jour_ferie', 'action', 'champ_modifie', 'ancienne_valeur',
        'nouvelle_valeur', 'motif', 'effectue_par', 'date_action'
    ]
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    @admin.display(description='Action')
    def badge_action(self, obj):
        colors = {
            'CREATION': '#27ae60',
            'MODIFICATION': '#3498db',
            'SUPPRESSION': '#e74c3c',
            'RESTAURATION': '#9b59b6',
        }
        icons = {
            'CREATION': '➕',
            'MODIFICATION': '✏️',
            'SUPPRESSION': '🗑️',
            'RESTAURATION': '♻️',
        }
        color = colors.get(obj.action, '#95a5a6')
        icon = icons.get(obj.action, '❓')
        return format_html(
            '<span style="background:{}; color:white; padding:2px 6px; border-radius:3px;">{} {}</span>',
            color, icon, obj.get_action_display()
        )
    
    @admin.display(description='Ancienne valeur')
    def ancienne_valeur_courte(self, obj):
        if obj.ancienne_valeur:
            return obj.ancienne_valeur[:30] + '...' if len(obj.ancienne_valeur) > 30 else obj.ancienne_valeur
        return '-'
    
    @admin.display(description='Nouvelle valeur')
    def nouvelle_valeur_courte(self, obj):
        if obj.nouvelle_valeur:
            return obj.nouvelle_valeur[:30] + '...' if len(obj.nouvelle_valeur) > 30 else obj.nouvelle_valeur
        return '-'


# ================================================================
# ACTIONS GLOBALES POUR GÉNÉRATION DES JOURS FÉRIÉS
# ================================================================

# Ces actions peuvent être ajoutées à d'autres admins si nécessaire

def generer_jours_feries_action(annee):
    """Factory pour créer des actions de génération"""
    @admin.action(description=f"📅 Générer jours fériés {annee}")
    def action(modeladmin, request, queryset):
        ModeleJourFerie.objects.charger_donnees_initiales()
        resultats = JourFerie.objects.generer_annee(annee, utilisateur=request.user.username)
        nb_crees = len(resultats.get('crees', []))
        if nb_crees > 0:
            modeladmin.message_user(request, f"✅ {nb_crees} jour(s) férié(s) créé(s) pour {annee}")
        else:
            modeladmin.message_user(request, f"ℹ️ Jours fériés {annee} déjà existants")
    return action

@admin.register(SignalementDateFerie)
class SignalementDateFerieAdmin(admin.ModelAdmin):
    '''Administration des signalements de dates'''
    
    list_display = [
        'jour_ferie', 'date_suggeree', 'source_info', 
        'signale_par', 'badge_statut', 'date_signalement'
    ]
    list_filter = ['statut', 'date_signalement', 'jour_ferie__type_ferie']
    search_fields = ['jour_ferie__nom', 'source_info', 'commentaire']
    ordering = ['-date_signalement']
    date_hierarchy = 'date_signalement'
    
    readonly_fields = ['signale_par', 'date_signalement', 'traite_par', 'date_traitement']
    
    fieldsets = (
        ('Signalement', {
            'fields': ('jour_ferie', 'date_suggeree', 'source_info', 'commentaire')
        }),
        ('Auteur', {
            'fields': ('signale_par', 'date_signalement')
        }),
        ('Traitement', {
            'fields': ('statut', 'traite_par', 'date_traitement')
        }),
    )
    
    actions = ['accepter_signalements', 'rejeter_signalements']
    
    @admin.display(description='Statut')
    def badge_statut(self, obj):
        colors = {
            'EN_ATTENTE': '#f59e0b',
            'ACCEPTE': '#10b981',
            'REJETE': '#ef4444',
        }
        color = colors.get(obj.statut, '#6b7280')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; border-radius:4px;">{}</span>',
            color, obj.get_statut_display()
        )
    
    @admin.action(description="✅ Accepter les signalements sélectionnés")
    def accepter_signalements(self, request, queryset):
        from django.utils import timezone
        from django.core.cache import cache
        
        count = 0
        for signalement in queryset.filter(statut='EN_ATTENTE'):
            try:
                signalement.jour_ferie.modifier_date(
                    nouvelle_date=signalement.date_suggeree,
                    motif=f"Signalement accepté. Source: {signalement.source_info}",
                    utilisateur=request.user.username
                )
                signalement.statut = 'ACCEPTE'
                signalement.traite_par = request.user.profilutilisateur
                signalement.date_traitement = timezone.now()
                signalement.save()
                count += 1
            except Exception as e:
                self.message_user(request, f"Erreur pour {signalement}: {e}", level=messages.ERROR)
        
        cache.delete('prochain_ferie_context')
        self.message_user(request, f"✅ {count} signalement(s) accepté(s)")
    
    @admin.action(description="❌ Rejeter les signalements sélectionnés")
    def rejeter_signalements(self, request, queryset):
        from django.utils import timezone
        
        count = queryset.filter(statut='EN_ATTENTE').update(
            statut='REJETE',
            traite_par=request.user.profilutilisateur,
            date_traitement=timezone.now()
        )
        self.message_user(request, f"❌ {count} signalement(s) rejeté(s)")

# ================================================================
# LOG DE CONFIRMATION
# ================================================================

logger.info("✅ Administration des jours fériés chargée")
logger.info("   • ModeleJourFerie: Templates de jours fériés")
logger.info("   • JourFerie: Instances par année")
logger.info("   • HistoriqueModification: Traçabilité des changements")