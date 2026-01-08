from django import template

register = template.Library()

@register.filter
def score_css_class(score):
    """
    🎨 Filtre Django basé sur votre fonction _get_score_css_class existante
    Utilisation dans le template: {{ score|score_css_class }}
    """
    try:
        # Conversion sécurisée du score
        if score is None:
            score_int = 0
        elif isinstance(score, (int, float)):
            score_int = int(score)
        else:
            score_int = int(float(str(score)))
        
        # ✅ LOGIQUE IDENTIQUE à votre fonction _get_score_css_class
        if score_int >= 80:
            return 'excellent'
        elif score_int >= 60:
            return 'good'
        elif score_int >= 40:
            return 'average'
        else:
            return 'poor'
            
    except (ValueError, TypeError, AttributeError):
        return 'poor'  # Classe par défaut en cas d'erreur
    
@register.filter
def get_item(dictionary, key):
    """
    Récupère un élément d'un dictionnaire par clé
    Usage: {{ mon_dict|get_item:ma_cle }}
    """
    if not dictionary:
        return None
    
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    
    # Pour les objets avec des attributs
    try:
        return getattr(dictionary, key, None)
    except (AttributeError, TypeError):
        return None

@register.filter
def multiply(value, arg):
    """
    Multiplie deux valeurs
    Usage: {{ value|multiply:arg }}
    """
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def percentage(value, total):
    """
    Calcule un pourcentage
    Usage: {{ value|percentage:total }}
    """
    try:
        if total == 0:
            return 0
        return (float(value) / float(total)) * 100
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def status_icon(status):
    """
    Retourne une icône selon le statut
    Usage: {{ status|status_icon }}
    """
    icons = {
        'ACTIF': 'fas fa-check-circle text-success',
        'INACTIF': 'fas fa-times-circle text-danger',
        'EN_COURS': 'fas fa-play-circle text-primary',
        'TERMINE': 'fas fa-check-circle text-success',
        'REFUSE': 'fas fa-times-circle text-danger',
        'EN_VALIDATION': 'fas fa-clock text-warning',
        'SOUMISE': 'fas fa-paper-plane text-info',
    }
    return mark_safe(f'<i class="{icons.get(status, "fas fa-question-circle text-muted")}"></i>')

@register.filter
def urgence_badge(urgence):
    """
    Retourne un badge coloré selon l'urgence
    Usage: {{ urgence|urgence_badge }}
    """
    badges = {
        'NORMALE': 'badge bg-success',
        'MOYENNE': 'badge bg-info', 
        'ELEVEE': 'badge bg-warning',
        'CRITIQUE': 'badge bg-danger',
    }
    
    classe = badges.get(urgence, 'badge bg-secondary')
    return mark_safe(f'<span class="{classe}">{urgence}</span>')

@register.filter
def score_class(score):
    """
    Retourne une classe CSS selon le score
    Usage: {{ score|score_class }}
    """
    try:
        score_val = float(score)
        if score_val >= 80:
            return 'excellent'
        elif score_val >= 65:
            return 'good'
        elif score_val >= 50:
            return 'average'
        else:
            return 'poor'
    except (ValueError, TypeError):
        return 'poor'

@register.filter
def duration_display(days):
    """
    Affiche une durée en jours de façon lisible
    Usage: {{ days|duration_display }}
    """
    try:
        days_val = int(days)
        if days_val == 0:
            return "Moins d'un jour"
        elif days_val == 1:
            return "1 jour"
        elif days_val < 7:
            return f"{days_val} jours"
        elif days_val < 30:
            weeks = days_val // 7
            remaining_days = days_val % 7
            if remaining_days == 0:
                return f"{weeks} semaine{'s' if weeks > 1 else ''}"
            else:
                return f"{weeks} semaine{'s' if weeks > 1 else ''} et {remaining_days} jour{'s' if remaining_days > 1 else ''}"
        else:
            months = days_val // 30
            remaining_days = days_val % 30
            if remaining_days == 0:
                return f"{months} mois"
            else:
                return f"{months} mois et {remaining_days} jour{'s' if remaining_days > 1 else ''}"
    except (ValueError, TypeError):
        return "Durée inconnue"

@register.filter
def json_encode(value):
    """
    Encode une valeur en JSON pour JavaScript
    Usage: {{ ma_variable|json_encode }}
    """
    try:
        return mark_safe(json.dumps(value))
    except (TypeError, ValueError):
        return mark_safe('null')

@register.filter
def truncate_words_html(value, arg):
    """
    Tronque un texte HTML en préservant les balises
    Usage: {{ text|truncate_words_html:30 }}
    """
    try:
        from django.utils.text import Truncator
        truncator = Truncator(value)
        return truncator.words(int(arg), html=True)
    except (ValueError, TypeError):
        return value

@register.filter
def add_class(field, css_class):
    """
    Ajoute une classe CSS à un champ de formulaire
    Usage: {{ form.field|add_class:"form-control" }}
    """
    try:
        return field.as_widget(attrs={"class": css_class})
    except AttributeError:
        return field

@register.filter
def default_if_none_or_empty(value, default):
    """
    Retourne une valeur par défaut si la valeur est None ou vide
    Usage: {{ value|default_if_none_or_empty:"Valeur par défaut" }}
    """
    if value is None or value == "" or (hasattr(value, '__len__') and len(value) == 0):
        return default
    return value

@register.simple_tag
def query_string(request, **kwargs):
    """
    Génère une query string en modifiant les paramètres existants
    Usage: {% query_string request page=2 sort="name" %}
    """
    query_dict = request.GET.copy()
    for key, value in kwargs.items():
        if value is None:
            query_dict.pop(key, None)
        else:
            query_dict[key] = value
    
    if query_dict:
        return f"?{query_dict.urlencode()}"
    return ""

@register.inclusion_tag('interim/components/pagination.html')
def render_pagination(page_obj, request):
    """
    Affiche la pagination
    Usage: {% render_pagination page_obj request %}
    """
    return {
        'page_obj': page_obj,
        'request': request,
    }

@register.filter
def range_filter(value):
    """
    Génère une range pour les boucles
    Usage: {% for i in 5|range_filter %}
    """
    try:
        return range(int(value))
    except (ValueError, TypeError):
        return range(0)

@register.filter
def dict_get(dictionary, key):
    """
    Alias pour get_item pour compatibilité
    Usage: {{ mon_dict|dict_get:ma_cle }}
    """
    return get_item(dictionary, key)

@register.filter
def format_matricule(matricule):
    """
    Formate un matricule de façon standardisée
    Usage: {{ matricule|format_matricule }}
    """
    if not matricule:
        return "N/A"
    
    # Convertir en string et nettoyer
    matricule_str = str(matricule).strip().upper()
    
    # Si c'est déjà au bon format, retourner tel quel
    if len(matricule_str) >= 3:
        return matricule_str
    
    # Sinon, padder avec des zéros
    return matricule_str.zfill(6)

@register.filter
def pluralize_fr(value, forms):
    """
    Pluralisation française
    Usage: {{ count|pluralize_fr:"candidat,candidats" }}
    """
    try:
        count = int(value)
        singular, plural = forms.split(',')
        return singular if count <= 1 else plural
    except (ValueError, TypeError):
        return forms.split(',')[0] if ',' in forms else forms

@register.filter
def boolean_icon(value):
    """
    Retourne une icône selon la valeur booléenne
    Usage: {{ is_available|boolean_icon }}
    """
    if value:
        return mark_safe('<i class="fas fa-check text-success"></i>')
    else:
        return mark_safe('<i class="fas fa-times text-danger"></i>')

@register.filter
def phone_format(phone):
    """
    Formate un numéro de téléphone
    Usage: {{ phone|phone_format }}
    """
    if not phone:
        return ""
    
    # Nettoyer le numéro
    cleaned = ''.join(filter(str.isdigit, str(phone)))
    
    # Format pour Côte d'Ivoire
    if len(cleaned) == 8:
        return f"{cleaned[:2]} {cleaned[2:4]} {cleaned[4:6]} {cleaned[6:8]}"
    elif len(cleaned) == 10 and cleaned.startswith('225'):
        return f"+225 {cleaned[3:5]} {cleaned[5:7]} {cleaned[7:9]} {cleaned[9:11]}"
    else:
        return phone  # Retourner tel quel si format non reconnu

@register.filter
def safe_divide(value, divisor):
    """
    Division sécurisée
    Usage: {{ value|safe_divide:divisor }}
    """
    try:
        if float(divisor) == 0:
            return 0
        return float(value) / float(divisor)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def strip_tags_truncate(value, length):
    """
    Supprime les tags HTML et tronque
    Usage: {{ html_content|strip_tags_truncate:100 }}
    """
    try:
        from django.utils.html import strip_tags
        from django.utils.text import Truncator
        
        plain_text = strip_tags(value)
        truncator = Truncator(plain_text)
        return truncator.chars(int(length))
    except (ValueError, TypeError):
        return value
    
