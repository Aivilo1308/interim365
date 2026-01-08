"""
Utilitaires sécurisés pour la gestion des dates et datetime
Évite les erreurs NoneType et les exceptions de formatage
Compatible avec le système Interim365 - BNI
"""

import logging
from datetime import datetime, date, timedelta
from typing import Optional, Union, Any
from django.utils import timezone
from django.utils.formats import date_format, time_format
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

# ================================================================
# FORMATAGE SÉCURISÉ DES DATES
# ================================================================

def safe_date_format(date_value: Optional[Union[date, datetime, str]], 
                    format_str: str = '%d/%m/%Y',
                    default_text: str = "Non renseignée",
                    use_django_format: bool = False) -> str:
    """
    Formate une date de manière sécurisée
    
    Args:
        date_value: Valeur de date à formatter (date, datetime, str ou None)
        format_str: Format de sortie (défaut: '%d/%m/%Y')
        default_text: Texte par défaut si date invalide
        use_django_format: Utiliser le formatage Django (respecte LANGUAGE_CODE)
    
    Returns:
        str: Date formatée ou texte par défaut
    """
    try:
        # Gérer les valeurs None ou vides
        if date_value is None:
            return default_text
            
        if isinstance(date_value, str):
            if not date_value.strip():
                return default_text
            # Tenter de parser la chaîne
            date_value = _parse_date_string(date_value)
            if date_value is None:
                return default_text
        
        # Vérifier que c'est bien un objet date/datetime
        if not isinstance(date_value, (date, datetime)):
            logger.warning(f"Type de date non supporté: {type(date_value)}")
            return default_text
        
        # Formatage avec Django si demandé
        if use_django_format:
            try:
                return date_format(date_value, format_str)
            except Exception as e:
                logger.debug(f"Erreur formatage Django, fallback vers strftime: {e}")
        
        # Formatage standard
        return date_value.strftime(format_str)
        
    except (AttributeError, ValueError, TypeError) as e:
        logger.debug(f"Erreur formatage date {date_value}: {e}")
        return default_text
    except Exception as e:
        logger.error(f"Erreur inattendue formatage date {date_value}: {e}")
        return "Date invalide"

def safe_datetime_format(datetime_value: Optional[Union[datetime, date, str]], 
                        format_str: str = '%d/%m/%Y %H:%M',
                        default_text: str = "Non renseigné",
                        use_django_format: bool = False,
                        timezone_aware: bool = True) -> str:
    """
    Formate un datetime de manière sécurisée
    
    Args:
        datetime_value: Valeur datetime à formatter
        format_str: Format de sortie (défaut: '%d/%m/%Y %H:%M')
        default_text: Texte par défaut si datetime invalide
        use_django_format: Utiliser le formatage Django
        timezone_aware: Convertir en timezone locale
    
    Returns:
        str: DateTime formaté ou texte par défaut
    """
    try:
        # Gérer les valeurs None ou vides
        if datetime_value is None:
            return default_text
            
        if isinstance(datetime_value, str):
            if not datetime_value.strip():
                return default_text
            # Tenter de parser la chaîne
            datetime_value = _parse_datetime_string(datetime_value)
            if datetime_value is None:
                return default_text
        
        # Convertir date en datetime si nécessaire
        if isinstance(datetime_value, date) and not isinstance(datetime_value, datetime):
            datetime_value = datetime.combine(datetime_value, datetime.min.time())
        
        # Vérifier que c'est bien un datetime
        if not isinstance(datetime_value, datetime):
            logger.warning(f"Type de datetime non supporté: {type(datetime_value)}")
            return default_text
        
        # Gestion timezone
        if timezone_aware and timezone.is_aware(datetime_value):
            # Convertir en timezone locale
            datetime_value = timezone.localtime(datetime_value)
        elif timezone_aware and not timezone.is_aware(datetime_value):
            # Rendre timezone-aware si nécessaire
            datetime_value = timezone.make_aware(datetime_value)
        
        # Formatage avec Django si demandé
        if use_django_format:
            try:
                # Séparer date et heure pour Django
                date_part = date_format(datetime_value, 'DATE_FORMAT')
                time_part = time_format(datetime_value, 'TIME_FORMAT')
                return f"{date_part} {time_part}"
            except Exception as e:
                logger.debug(f"Erreur formatage Django datetime, fallback: {e}")
        
        # Formatage standard
        return datetime_value.strftime(format_str)
        
    except (AttributeError, ValueError, TypeError) as e:
        logger.debug(f"Erreur formatage datetime {datetime_value}: {e}")
        return default_text
    except Exception as e:
        logger.error(f"Erreur inattendue formatage datetime {datetime_value}: {e}")
        return "DateTime invalide"

# ================================================================
# OPÉRATIONS SÉCURISÉES SUR LES DATES
# ================================================================

def safe_date_operation(date1: Optional[Union[date, datetime]], 
                       date2: Optional[Union[date, datetime]], 
                       operation: str = 'subtract') -> Optional[Union[int, date, datetime]]:
    """
    Effectue une opération sécurisée entre deux dates
    
    Args:
        date1: Première date
        date2: Deuxième date ou timedelta
        operation: Type d'opération ('subtract', 'add', 'compare')
    
    Returns:
        Résultat de l'opération ou None si erreur
    """
    try:
        if date1 is None or date2 is None:
            return None
        
        # Convertir les chaînes si nécessaire
        if isinstance(date1, str):
            date1 = _parse_date_string(date1)
        if isinstance(date2, str):
            date2 = _parse_date_string(date2)
        
        if date1 is None or date2 is None:
            return None
        
        # Normaliser les types (date vs datetime)
        date1, date2 = _normalize_date_types(date1, date2)
        
        if operation == 'subtract':
            # Retourne la différence en jours
            delta = date1 - date2
            return delta.days
            
        elif operation == 'add':
            # Ajoute une durée (date2 doit être un timedelta ou int)
            if isinstance(date2, int):
                return date1 + timedelta(days=date2)
            elif isinstance(date2, timedelta):
                return date1 + date2
            else:
                return date1 + date2
                
        elif operation == 'compare':
            # Compare deux dates (-1, 0, 1)
            if date1 < date2:
                return -1
            elif date1 > date2:
                return 1
            else:
                return 0
                
        else:
            logger.warning(f"Opération non supportée: {operation}")
            return None
            
    except (TypeError, AttributeError, ValueError) as e:
        logger.debug(f"Erreur opération date {operation}: {e}")
        return None
    except Exception as e:
        logger.error(f"Erreur inattendue opération date: {e}")
        return None

def safe_date_diff_days(date1: Optional[Union[date, datetime]], 
                       date2: Optional[Union[date, datetime]]) -> int:
    """
    Calcule la différence en jours entre deux dates de manière sécurisée
    
    Returns:
        int: Nombre de jours (0 si erreur)
    """
    try:
        result = safe_date_operation(date1, date2, 'subtract')
        return result if result is not None else 0
    except:
        return 0

def safe_date_add_days(date_value: Optional[Union[date, datetime]], 
                      days: int) -> Optional[Union[date, datetime]]:
    """
    Ajoute des jours à une date de manière sécurisée
    """
    try:
        return safe_date_operation(date_value, days, 'add')
    except:
        return None

# ================================================================
# VALIDATION ET VÉRIFICATION DES DATES
# ================================================================

def is_valid_date(date_value: Any) -> bool:
    """
    Vérifie si une valeur est une date valide
    """
    try:
        if date_value is None:
            return False
            
        if isinstance(date_value, (date, datetime)):
            return True
            
        if isinstance(date_value, str):
            parsed = _parse_date_string(date_value)
            return parsed is not None
            
        return False
        
    except:
        return False

def is_date_in_range(date_value: Optional[Union[date, datetime]], 
                    start_date: Optional[Union[date, datetime]], 
                    end_date: Optional[Union[date, datetime]]) -> bool:
    """
    Vérifie si une date est dans une plage donnée
    """
    try:
        if not all([is_valid_date(d) for d in [date_value, start_date, end_date]]):
            return False
        
        # Normaliser les types
        date_value, start_date = _normalize_date_types(date_value, start_date)
        date_value, end_date = _normalize_date_types(date_value, end_date)
        
        return start_date <= date_value <= end_date
        
    except:
        return False

def is_business_day(date_value: Optional[Union[date, datetime]]) -> bool:
    """
    Vérifie si une date est un jour ouvrable (lun-ven)
    """
    try:
        if not is_valid_date(date_value):
            return False
            
        if isinstance(date_value, str):
            date_value = _parse_date_string(date_value)
            
        if isinstance(date_value, datetime):
            date_value = date_value.date()
            
        # 0=lundi, 6=dimanche
        return date_value.weekday() < 5
        
    except:
        return False

def is_weekend(date_value: Optional[Union[date, datetime]]) -> bool:
    """
    Vérifie si une date est un weekend
    """
    return not is_business_day(date_value) if is_valid_date(date_value) else False

# ================================================================
# FORMATAGE SPÉCIALISÉ POUR L'APPLICATION
# ================================================================

def format_duree_mission(date_debut: Optional[Union[date, datetime]], 
                        date_fin: Optional[Union[date, datetime]]) -> str:
    """
    Formate la durée d'une mission
    """
    try:
        if not date_debut or not date_fin:
            return "Durée non définie"
            
        duree = safe_date_diff_days(date_fin, date_debut) + 1  # +1 pour inclure le dernier jour
        
        if duree <= 0:
            return "Durée invalide"
        elif duree == 1:
            return "1 jour"
        elif duree < 7:
            return f"{duree} jours"
        elif duree < 30:
            semaines = duree // 7
            jours_restants = duree % 7
            if jours_restants == 0:
                return f"{semaines} semaine{'s' if semaines > 1 else ''}"
            else:
                return f"{semaines} semaine{'s' if semaines > 1 else ''} et {jours_restants} jour{'s' if jours_restants > 1 else ''}"
        else:
            mois = duree // 30
            jours_restants = duree % 30
            if jours_restants == 0:
                return f"{mois} mois"
            else:
                return f"{mois} mois et {jours_restants} jour{'s' if jours_restants > 1 else ''}"
                
    except Exception as e:
        logger.debug(f"Erreur formatage durée mission: {e}")
        return "Durée indéterminée"

def format_periode_mission(date_debut: Optional[Union[date, datetime]], 
                          date_fin: Optional[Union[date, datetime]]) -> str:
    """
    Formate la période d'une mission
    """
    try:
        debut_str = safe_date_format(date_debut, '%d/%m/%Y', 'À définir')
        fin_str = safe_date_format(date_fin, '%d/%m/%Y', 'À définir')
        
        if debut_str == 'À définir' and fin_str == 'À définir':
            return "Période à définir"
        elif debut_str == 'À définir':
            return f"Jusqu'au {fin_str}"
        elif fin_str == 'À définir':
            return f"À partir du {debut_str}"
        else:
            return f"Du {debut_str} au {fin_str}"
            
    except Exception as e:
        logger.debug(f"Erreur formatage période mission: {e}")
        return "Période indéterminée"

def format_delai_reponse(date_limite: Optional[Union[datetime, date]]) -> str:
    """
    Formate le délai de réponse restant
    """
    try:
        if not date_limite:
            return "Délai non défini"
            
        if isinstance(date_limite, str):
            date_limite = _parse_datetime_string(date_limite)
            
        if not isinstance(date_limite, datetime):
            return "Délai invalide"
        
        now = timezone.now()
        if timezone.is_naive(date_limite):
            date_limite = timezone.make_aware(date_limite)
            
        diff = date_limite - now
        
        if diff.total_seconds() <= 0:
            return "⏰ Délai dépassé"
        
        total_seconds = int(diff.total_seconds())
        
        if total_seconds < 3600:  # Moins d'une heure
            minutes = total_seconds // 60
            return f"⏱️ {minutes} minute{'s' if minutes > 1 else ''}"
        elif total_seconds < 86400:  # Moins d'un jour
            heures = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            if minutes == 0:
                return f"⏰ {heures}h"
            else:
                return f"⏰ {heures}h{minutes:02d}"
        else:  # Plus d'un jour
            jours = total_seconds // 86400
            heures = (total_seconds % 86400) // 3600
            if heures == 0:
                return f"📅 {jours} jour{'s' if jours > 1 else ''}"
            else:
                return f"📅 {jours}j {heures}h"
                
    except Exception as e:
        logger.debug(f"Erreur formatage délai réponse: {e}")
        return "Délai inconnu"

def format_anciennete(date_embauche: Optional[Union[date, datetime]]) -> str:
    """
    Formate l'ancienneté depuis la date d'embauche
    """
    try:
        if not date_embauche:
            return "Ancienneté non renseignée"
            
        today = timezone.now().date()
        if isinstance(date_embauche, datetime):
            date_embauche = date_embauche.date()
        elif isinstance(date_embauche, str):
            parsed = _parse_date_string(date_embauche)
            if parsed:
                date_embauche = parsed.date() if isinstance(parsed, datetime) else parsed
            else:
                return "Date d'embauche invalide"
        
        if date_embauche > today:
            return "Date d'embauche future"
            
        diff = today - date_embauche
        jours = diff.days
        
        if jours < 30:
            return f"{jours} jour{'s' if jours > 1 else ''}"
        elif jours < 365:
            mois = jours // 30
            return f"{mois} mois"
        else:
            annees = jours // 365
            mois_restants = (jours % 365) // 30
            if mois_restants == 0:
                return f"{annees} an{'s' if annees > 1 else ''}"
            else:
                return f"{annees} an{'s' if annees > 1 else ''} et {mois_restants} mois"
                
    except Exception as e:
        logger.debug(f"Erreur formatage ancienneté: {e}")
        return "Ancienneté indéterminée"

def format_age(date_naissance: Optional[Union[date, datetime]]) -> str:
    """
    Formate l'âge depuis la date de naissance
    """
    try:
        if not date_naissance:
            return "Âge non renseigné"
            
        today = timezone.now().date()
        if isinstance(date_naissance, datetime):
            date_naissance = date_naissance.date()
        elif isinstance(date_naissance, str):
            parsed = _parse_date_string(date_naissance)
            if parsed:
                date_naissance = parsed.date() if isinstance(parsed, datetime) else parsed
            else:
                return "Date de naissance invalide"
        
        if date_naissance > today:
            return "Date de naissance future"
            
        age = today.year - date_naissance.year
        
        # Ajuster si l'anniversaire n'est pas encore passé cette année
        if (today.month, today.day) < (date_naissance.month, date_naissance.day):
            age -= 1
            
        return f"{age} ans"
        
    except Exception as e:
        logger.debug(f"Erreur formatage âge: {e}")
        return "Âge indéterminé"

# ================================================================
# FORMATAGE POUR L'AFFICHAGE ADMIN ET HISTORIQUE
# ================================================================

def format_date_creation(created_at: Optional[datetime]) -> str:
    """
    Formate une date de création avec contexte temporel
    """
    try:
        if not created_at:
            return "Date inconnue"
            
        now = timezone.now()
        if timezone.is_naive(created_at):
            created_at = timezone.make_aware(created_at)
            
        diff = now - created_at
        
        if diff.days == 0:
            # Aujourd'hui
            if diff.seconds < 3600:
                minutes = diff.seconds // 60
                return f"Il y a {minutes} minute{'s' if minutes > 1 else ''}"
            else:
                heures = diff.seconds // 3600
                return f"Il y a {heures} heure{'s' if heures > 1 else ''}"
        elif diff.days == 1:
            return f"Hier à {safe_datetime_format(created_at, '%H:%M')}"
        elif diff.days < 7:
            return f"Il y a {diff.days} jours"
        elif diff.days < 30:
            semaines = diff.days // 7
            return f"Il y a {semaines} semaine{'s' if semaines > 1 else ''}"
        else:
            return safe_datetime_format(created_at, '%d/%m/%Y')
            
    except Exception as e:
        logger.debug(f"Erreur formatage date création: {e}")
        return "Date indéterminée"

def format_derniere_activite(last_activity: Optional[datetime]) -> str:
    """
    Formate la dernière activité
    """
    try:
        if not last_activity:
            return "Jamais"
            
        return format_date_creation(last_activity)
        
    except Exception as e:
        logger.debug(f"Erreur formatage dernière activité: {e}")
        return "Inconnue"

# ================================================================
# CALCULS DE DATES MÉTIER
# ================================================================

def calculer_date_fin_mission(date_debut: Optional[Union[date, datetime]], 
                             duree_jours: int) -> Optional[date]:
    """
    Calcule la date de fin d'une mission
    """
    try:
        if not date_debut or duree_jours <= 0:
            return None
            
        if isinstance(date_debut, str):
            date_debut = _parse_date_string(date_debut)
            
        if isinstance(date_debut, datetime):
            date_debut = date_debut.date()
            
        return date_debut + timedelta(days=duree_jours - 1)  # -1 car le premier jour compte
        
    except Exception as e:
        logger.debug(f"Erreur calcul date fin mission: {e}")
        return None

def calculer_prochaine_date_ouvrable(date_reference: Optional[Union[date, datetime]], 
                                   jours_ouvres: int = 1) -> Optional[date]:
    """
    Calcule la prochaine date ouvrable
    """
    try:
        if not date_reference:
            date_reference = timezone.now().date()
        elif isinstance(date_reference, datetime):
            date_reference = date_reference.date()
        elif isinstance(date_reference, str):
            parsed = _parse_date_string(date_reference)
            if parsed:
                date_reference = parsed.date() if isinstance(parsed, datetime) else parsed
            else:
                return None
                
        current_date = date_reference
        jours_ajoutes = 0
        
        while jours_ajoutes < jours_ouvres:
            current_date += timedelta(days=1)
            if is_business_day(current_date):
                jours_ajoutes += 1
                
        return current_date
        
    except Exception as e:
        logger.debug(f"Erreur calcul prochaine date ouvrable: {e}")
        return None

def est_dans_periode_urgente(date_limite: Optional[Union[datetime, date]], 
                           seuil_heures: int = 24) -> bool:
    """
    Vérifie si on est dans une période urgente avant une date limite
    """
    try:
        if not date_limite:
            return False
            
        if isinstance(date_limite, str):
            date_limite = _parse_datetime_string(date_limite)
            
        if isinstance(date_limite, date) and not isinstance(date_limite, datetime):
            # Convertir en datetime en fin de journée
            date_limite = datetime.combine(date_limite, datetime.max.time())
            
        if timezone.is_naive(date_limite):
            date_limite = timezone.make_aware(date_limite)
            
        now = timezone.now()
        diff = date_limite - now
        
        return 0 < diff.total_seconds() <= (seuil_heures * 3600)
        
    except Exception as e:
        logger.debug(f"Erreur vérification période urgente: {e}")
        return False

# ================================================================
# FONCTIONS UTILITAIRES PRIVÉES
# ================================================================

def _parse_date_string(date_str: str) -> Optional[Union[date, datetime]]:
    """
    Parse une chaîne de date avec plusieurs formats possibles
    """
    if not date_str or not isinstance(date_str, str):
        return None
        
    # Formats supportés
    formats = [
        '%Y-%m-%d',           # 2024-12-25
        '%d/%m/%Y',           # 25/12/2024
        '%d-%m-%Y',           # 25-12-2024
        '%Y-%m-%d %H:%M:%S',  # 2024-12-25 14:30:00
        '%d/%m/%Y %H:%M',     # 25/12/2024 14:30
        '%Y-%m-%dT%H:%M:%S',  # ISO format
        '%Y-%m-%dT%H:%M:%SZ', # ISO with Z
    ]
    
    date_str = date_str.strip()
    
    for fmt in formats:
        try:
            if 'T' in fmt and 'T' in date_str:
                # Gérer les formats ISO avec timezone
                if date_str.endswith('Z'):
                    date_str = date_str[:-1]
                elif '+' in date_str:
                    date_str = date_str.split('+')[0]
                    
            parsed = datetime.strptime(date_str, fmt)
            
            # Retourner date si pas d'heure, sinon datetime
            if '%H' not in fmt:
                return parsed.date()
            else:
                return parsed
                
        except ValueError:
            continue
            
    return None

def _parse_datetime_string(datetime_str: str) -> Optional[datetime]:
    """
    Parse une chaîne de datetime
    """
    parsed = _parse_date_string(datetime_str)
    
    if isinstance(parsed, date) and not isinstance(parsed, datetime):
        # Convertir date en datetime
        return datetime.combine(parsed, datetime.min.time())
    elif isinstance(parsed, datetime):
        return parsed
    else:
        return None

def _normalize_date_types(date1: Union[date, datetime], 
                         date2: Union[date, datetime]) -> tuple:
    """
    Normalise deux dates au même type (date ou datetime)
    """
    try:
        # Si les deux sont datetime, on garde datetime
        if isinstance(date1, datetime) and isinstance(date2, datetime):
            return date1, date2
            
        # Si l'un est datetime et l'autre date, convertir date en datetime
        if isinstance(date1, datetime) and isinstance(date2, date):
            date2 = datetime.combine(date2, datetime.min.time())
            return date1, date2
            
        if isinstance(date1, date) and isinstance(date2, datetime):
            date1 = datetime.combine(date1, datetime.min.time())
            return date1, date2
            
        # Si les deux sont date, on garde date
        if isinstance(date1, date) and isinstance(date2, date):
            return date1, date2
            
        return date1, date2
        
    except Exception:
        return date1, date2

# ================================================================
# TEMPLATE FILTERS DJANGO (optionnel)
# ================================================================

def register_template_filters():
    """
    Enregistre les filtres de template Django
    À utiliser dans templatetags/date_filters.py
    """
    from django import template
    
    register = template.Library()
    
    @register.filter
    def safe_date(value, format_str='%d/%m/%Y'):
        return safe_date_format(value, format_str)
    
    @register.filter
    def safe_datetime(value, format_str='%d/%m/%Y %H:%M'):
        return safe_datetime_format(value, format_str)
    
    @register.filter
    def duree_mission(date_debut, date_fin):
        return format_duree_mission(date_debut, date_fin)
    
    @register.filter
    def periode_mission(date_debut, date_fin):
        return format_periode_mission(date_debut, date_fin)
    
    @register.filter
    def delai_reponse(date_limite):
        return format_delai_reponse(date_limite)
    
    @register.filter
    def anciennete(date_embauche):
        return format_anciennete(date_embauche)
    
    @register.filter
    def date_creation(created_at):
        return format_date_creation(created_at)
    
    @register.filter
    def est_urgent(date_limite, seuil=24):
        return est_dans_periode_urgente(date_limite, int(seuil))
    
    return register

# ================================================================
# FONCTIONS D'EXPORT ET IMPORT
# ================================================================

def export_dates_to_dict(obj: Any, 
                        date_fields: list, 
                        format_str: str = '%Y-%m-%d') -> dict:
    """
    Exporte les champs de date d'un objet vers un dictionnaire
    """
    result = {}
    
    for field in date_fields:
        try:
            value = getattr(obj, field, None)
            if value:
                result[field] = safe_date_format(value, format_str, None)
            else:
                result[field] = None
        except Exception as e:
            logger.debug(f"Erreur export date {field}: {e}")
            result[field] = None
            
    return result

def import_dates_from_dict(data: dict, 
                          date_fields: list) -> dict:
    """
    Importe les dates depuis un dictionnaire avec validation
    """
    result = {}
    
    for field in date_fields:
        try:
            value = data.get(field)
            if value:
                parsed = _parse_date_string(str(value))
                result[field] = parsed
            else:
                result[field] = None
        except Exception as e:
            logger.debug(f"Erreur import date {field}: {e}")
            result[field] = None
            
    return result

# ================================================================
# CONFIGURATION ET CONSTANTES
# ================================================================

# Formats par défaut pour différents contextes
DEFAULT_FORMATS = {
    'date_short': '%d/%m/%Y',
    'date_long': '%A %d %B %Y',
    'datetime_short': '%d/%m/%Y %H:%M',
    'datetime_long': '%A %d %B %Y à %H:%M:%S',
    'time_only': '%H:%M',
    'time_with_seconds': '%H:%M:%S',
    'iso_date': '%Y-%m-%d',
    'iso_datetime': '%Y-%m-%dT%H:%M:%S',
    'filename_safe': '%Y%m%d_%H%M%S'
}

# Messages par défaut
DEFAULT_MESSAGES = {
    'date_none': 'Non renseignée',
    'datetime_none': 'Non renseigné',
    'date_invalid': 'Date invalide',
    'datetime_invalid': 'DateTime invalide',
    'duree_indefinie': 'Durée indéfinie',
    'periode_indefinie': 'Période indéfinie',
    'delai_expire': 'Délai dépassé',
    'anciennete_inconnue': 'Ancienneté inconnue'
}

def get_format(format_name: str) -> str:
    """
    Récupère un format prédéfini
    """
    return DEFAULT_FORMATS.get(format_name, '%d/%m/%Y')

def get_message(message_name: str) -> str:
    """
    Récupère un message prédéfini
    """
    return DEFAULT_MESSAGES.get(message_name, 'Non défini')

# ================================================================
# FONCTIONS DE TEST ET DEBUG
# ================================================================

def test_date_formats():
    """
    Fonction de test pour vérifier les formats de date
    """
    test_cases = [
        None,
        '',
        '2024-12-25',
        '25/12/2024',
        '2024-12-25 14:30:00',
        'invalid_date',
        datetime.now(),
        date.today(),
    ]
    
    print("=== Test des formats de date ===")
    for test_case in test_cases:
        result = safe_date_format(test_case)
        print(f"{test_case} -> {result}")
    
    print("\n=== Test des formats de datetime ===")
    for test_case in test_cases:
        result = safe_datetime_format(test_case)
        print(f"{test_case} -> {result}")

if __name__ == '__main__':
    # Exécuter les tests si le module est appelé directement
    test_date_formats()