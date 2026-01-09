# -*- coding: utf-8 -*-
"""
Vues pour l'extraction des absences utilisateurs avec jours fériés

Fichier à placer dans: mainapp/views_absences_extraction.py

Fonctionnalités:
- Liste des absences avec indication des jours fériés dans la période
- Filtrage par département, site, matricule, période
- Export PDF, XLSX, CSV
"""

from datetime import date, datetime, timedelta
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.db.models import Q
from django.core.paginator import Paginator
import io
import csv
import logging

logger = logging.getLogger(__name__)



def get_feries_dans_periode(date_debut, date_fin, code_pays='CI'):
    """
    Retourne la liste des jours fériés dans une période donnée
    
    Args:
        date_debut: Date de début de la période
        date_fin: Date de fin de la période
        code_pays: Code pays (défaut: CI)
        
    Returns:
        Liste de dictionnaires avec les infos des jours fériés
    """
    from mainapp.models import JourFerie
    
    try:
        feries = JourFerie.objects.filter(
            date_ferie__gte=date_debut,
            date_ferie__lte=date_fin,
            code_pays=code_pays,
            statut='ACTIF'
        ).order_by('date_ferie')
        
        return [
            {
                'date': f.date_ferie,
                'nom': f.nom,
                'type': f.get_type_ferie_display(),
            }
            for f in feries
        ]
    except Exception as e:
        logger.error(f"Erreur récupération jours fériés: {e}")
        return []


def compter_feries_dans_periode(date_debut, date_fin, code_pays='CI'):
    """Compte le nombre de jours fériés dans une période"""
    from mainapp.models import JourFerie
    
    try:
        return JourFerie.objects.filter(
            date_ferie__gte=date_debut,
            date_ferie__lte=date_fin,
            code_pays=code_pays,
            statut='ACTIF'
        ).count()
    except Exception:
        return 0


def formater_feries_pour_affichage(feries):
    """Formate la liste des jours fériés pour l'affichage"""
    if not feries:
        return "-"
    
    return ", ".join([
        f"{f['nom']} ({f['date'].strftime('%d/%m')})"
        for f in feries
    ])


@login_required
def absences_extraction_liste(request):
    """
    Vue principale pour l'extraction des absences avec jours fériés
    
    URL: /interim/extraction/
    Template: extraction_absences_liste.html
    """
    from mainapp.models import AbsenceUtilisateur, Departement, Site, ProfilUtilisateur
    
    # Paramètres de filtrage
    departement_id = request.GET.get('departement', '')
    site_id = request.GET.get('site', '')
    matricule = request.GET.get('matricule', '').strip()
    type_absence = request.GET.get('type_absence', '')
    date_debut_str = request.GET.get('date_debut', '')
    date_fin_str = request.GET.get('date_fin', '')
    statut_filtre = request.GET.get('statut', '')
    annee_filtre = request.GET.get('annee', '')
    tri = request.GET.get('tri', 'date_desc')
    
    # Options de tri disponibles
    OPTIONS_TRI = {
        'matricule_asc': ('utilisateur__matricule', 'Matricule (A → Z)'),
        'matricule_desc': ('-utilisateur__matricule', 'Matricule (Z → A)'),
        'nom_asc': ('utilisateur__user__last_name', 'utilisateur__user__first_name', 'Nom (A → Z)'),
        'nom_desc': ('-utilisateur__user__last_name', '-utilisateur__user__first_name', 'Nom (Z → A)'),
        'date_asc': ('date_debut', 'Date début (ancien → récent)'),
        'date_desc': ('-date_debut', 'Date début (récent → ancien)'),
        'motif_asc': ('type_absence', 'Motif (A → Z)'),
        'motif_desc': ('-type_absence', 'Motif (Z → A)'),
    }
    
    today = date.today()
    annee_courante = today.year
    
    # Année sélectionnée (zone de saisie)
    if annee_filtre:
        try:
            annee_selectionnee = int(annee_filtre)
            # Validation de l'année (entre 2000 et 2100)
            if annee_selectionnee < 2000 or annee_selectionnee > 2100:
                annee_selectionnee = annee_courante
        except ValueError:
            annee_selectionnee = annee_courante
    else:
        annee_selectionnee = annee_courante
    
    # Dates par défaut selon l'année sélectionnée
    if not date_debut_str:
        date_debut = date(annee_selectionnee, 1, 1)
    else:
        try:
            date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date()
        except ValueError:
            date_debut = date(annee_selectionnee, 1, 1)
    
    if not date_fin_str:
        date_fin = date(annee_selectionnee, 12, 31)
    else:
        try:
            date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date()
        except ValueError:
            date_fin = date(annee_selectionnee, 12, 31)
    
    # Requête de base - filtrée par plage de dates
    absences = AbsenceUtilisateur.objects.select_related(
        'utilisateur',
        'utilisateur__departement',
        'utilisateur__site',
        'utilisateur__user'
    ).filter(
        # Absences qui chevauchent la période sélectionnée
        Q(date_debut__lte=date_fin) & Q(date_fin__gte=date_debut)
    )
    
    # Appliquer l'ordre de tri
    if tri in OPTIONS_TRI:
        tri_info = OPTIONS_TRI[tri]
        if tri.startswith('nom_'):
            absences = absences.order_by(tri_info[0], tri_info[1])
        else:
            absences = absences.order_by(tri_info[0])
    else:
        absences = absences.order_by('-date_debut', 'utilisateur__user__last_name')
    
    # Filtrage par département
    if departement_id:
        try:
            absences = absences.filter(utilisateur__departement_id=int(departement_id))
        except ValueError:
            pass
    
    # Filtrage par site
    if site_id:
        try:
            absences = absences.filter(utilisateur__site_id=int(site_id))
        except ValueError:
            pass
    
    # Filtrage par matricule
    if matricule:
        absences = absences.filter(
            Q(utilisateur__matricule__icontains=matricule) |
            Q(utilisateur__user__first_name__icontains=matricule) |
            Q(utilisateur__user__last_name__icontains=matricule)
        )
    
    # Filtrage par type d'absence
    if type_absence:
        absences = absences.filter(type_absence__icontains=type_absence)
    
    # Enrichir les absences avec les jours fériés
    absences_avec_feries = []
    for absence in absences:
        feries = get_feries_dans_periode(absence.date_debut, absence.date_fin)
        absences_avec_feries.append({
            'absence': absence,
            'feries': feries,
            'nb_feries': len(feries),
            'feries_texte': formater_feries_pour_affichage(feries),
        })
    
    # Pagination
    page_number = request.GET.get('page', 1)
    per_page = request.GET.get('per_page', '25')
    
    OPTIONS_PER_PAGE = [10, 25, 50, 100, 200]
    
    try:
        per_page = int(per_page)
        if per_page not in OPTIONS_PER_PAGE:
            per_page = 25
    except (ValueError, TypeError):
        per_page = 25
    
    paginator = Paginator(absences_avec_feries, per_page)
    page_obj = paginator.get_page(page_number)
    
    # Données pour les filtres
    departements = Departement.objects.filter(actif=True).order_by('nom')
    sites = Site.objects.filter(actif=True).order_by('nom')
    
    # Types d'absence distincts
    types_absence = AbsenceUtilisateur.objects.values_list(
        'type_absence', flat=True
    ).distinct().order_by('type_absence')
    
    # Statistiques
    stats = {
        'total_absences': len(absences_avec_feries),
        'total_jours': sum(a['absence'].duree_jours for a in absences_avec_feries),
        'absences_avec_feries': sum(1 for a in absences_avec_feries if a['nb_feries'] > 0),
        'total_feries_inclus': sum(a['nb_feries'] for a in absences_avec_feries),
    }
    
    # Préparer les options de tri pour le template
    options_tri_template = [
        ('date_desc', 'Date début (récent → ancien)'),
        ('date_asc', 'Date début (ancien → récent)'),
        ('matricule_asc', 'Matricule (A → Z)'),
        ('matricule_desc', 'Matricule (Z → A)'),
        ('nom_asc', 'Nom (A → Z)'),
        ('nom_desc', 'Nom (Z → A)'),
        ('motif_asc', 'Motif (A → Z)'),
        ('motif_desc', 'Motif (Z → A)'),
    ]
    
    context = {
        'page_obj': page_obj,
        'absences': page_obj.object_list,
        'departements': departements,
        'sites': sites,
        'types_absence': types_absence,
        'stats': stats,
        
        # Filtres actuels
        'departement_id': departement_id,
        'site_id': site_id,
        'matricule': matricule,
        'type_absence': type_absence,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'statut_filtre': statut_filtre,
        
        # Année
        'annee_selectionnee': annee_selectionnee,
        'annee_courante': annee_courante,
        
        # Tri
        'tri': tri,
        'options_tri': options_tri_template,
        
        # Pagination
        'per_page': per_page,
        'options_per_page': OPTIONS_PER_PAGE,
        
        'today': today,
    }
    
    return render(request, 'extraction_absences_liste.html', context)


@login_required
def absences_extraction_export(request, format_export):
    """
    Export des absences en PDF, XLSX ou CSV
    
    URL: /interim/extraction/export/<format>/
    Formats: pdf, xlsx, csv
    """
    from mainapp.models import AbsenceUtilisateur
    
    # Récupérer les mêmes filtres que la liste
    departement_id = request.GET.get('departement', '')
    site_id = request.GET.get('site', '')
    matricule = request.GET.get('matricule', '').strip()
    type_absence = request.GET.get('type_absence', '')
    date_debut_str = request.GET.get('date_debut', '')
    date_fin_str = request.GET.get('date_fin', '')
    annee_filtre = request.GET.get('annee', '')
    tri = request.GET.get('tri', 'date_desc')
    
    # Options de tri
    OPTIONS_TRI = {
        'matricule_asc': ('utilisateur__matricule',),
        'matricule_desc': ('-utilisateur__matricule',),
        'nom_asc': ('utilisateur__user__last_name', 'utilisateur__user__first_name'),
        'nom_desc': ('-utilisateur__user__last_name', '-utilisateur__user__first_name'),
        'date_asc': ('date_debut',),
        'date_desc': ('-date_debut',),
        'motif_asc': ('type_absence',),
        'motif_desc': ('-type_absence',),
    }
    
    today = date.today()
    annee_courante = today.year
    
    # Année sélectionnée
    try:
        annee_selectionnee = int(annee_filtre) if annee_filtre else annee_courante
        if annee_selectionnee < 2000 or annee_selectionnee > 2100:
            annee_selectionnee = annee_courante
    except ValueError:
        annee_selectionnee = annee_courante
    
    # Dates
    try:
        date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date() if date_debut_str else date(annee_selectionnee, 1, 1)
    except ValueError:
        date_debut = date(annee_selectionnee, 1, 1)
    
    try:
        date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date() if date_fin_str else date(annee_selectionnee, 12, 31)
    except ValueError:
        date_fin = date(annee_selectionnee, 12, 31)
    
    # Construire la requête
    absences = AbsenceUtilisateur.objects.select_related(
        'utilisateur',
        'utilisateur__departement',
        'utilisateur__site',
        'utilisateur__user'
    ).filter(
        Q(date_debut__lte=date_fin) & Q(date_fin__gte=date_debut)
    )
    
    # Appliquer l'ordre de tri
    if tri in OPTIONS_TRI:
        absences = absences.order_by(*OPTIONS_TRI[tri])
    else:
        absences = absences.order_by('-date_debut', 'utilisateur__user__last_name')
    
    # Appliquer les filtres
    if departement_id:
        try:
            absences = absences.filter(utilisateur__departement_id=int(departement_id))
        except ValueError:
            pass
    
    if site_id:
        try:
            absences = absences.filter(utilisateur__site_id=int(site_id))
        except ValueError:
            pass
    
    if matricule:
        absences = absences.filter(
            Q(utilisateur__matricule__icontains=matricule) |
            Q(utilisateur__user__first_name__icontains=matricule) |
            Q(utilisateur__user__last_name__icontains=matricule)
        )
    
    if type_absence:
        absences = absences.filter(type_absence__icontains=type_absence)
    
    # Préparer les données avec les jours fériés
    donnees = []
    for absence in absences:
        feries = get_feries_dans_periode(absence.date_debut, absence.date_fin)
        donnees.append({
            'matricule': absence.utilisateur.matricule,
            'nom': absence.utilisateur.user.last_name if absence.utilisateur.user else '',
            'prenom': absence.utilisateur.user.first_name if absence.utilisateur.user else '',
            'departement': absence.utilisateur.departement.nom if absence.utilisateur.departement else '',
            'site': absence.utilisateur.site.nom if absence.utilisateur.site else '',
            'date_debut': absence.date_debut,
            'date_fin': absence.date_fin,
            'duree_jours': absence.duree_jours,
            'type_absence': absence.type_absence,
            'feries': formater_feries_pour_affichage(feries),
            'nb_feries': len(feries),
        })
    
    # Nom du fichier
    filename = f"extraction_absences_{date_debut.strftime('%Y%m%d')}_{date_fin.strftime('%Y%m%d')}"
    
    if format_export == 'csv':
        return export_csv(donnees, filename)
    elif format_export == 'xlsx':
        return export_xlsx(donnees, filename, date_debut, date_fin)
    elif format_export == 'pdf':
        return export_pdf(donnees, filename, date_debut, date_fin)
    else:
        return HttpResponse("Format non supporté", status=400)


def export_csv(donnees, filename):
    """Export en CSV"""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
    
    # BOM UTF-8 pour Excel
    response.write('\ufeff')
    
    writer = csv.writer(response, delimiter=';')
    
    # En-têtes
    writer.writerow([
        'MATRICULE',
        'NOM',
        'PRENOM',
        'DEPARTEMENT',
        'SITE',
        'DATE DEPART',
        'DATE FIN',
        'NOMBRE DE JOURS',
        'MOTIF DE L\'ABSENCE',
        'JOURS FERIES INCLUS',
        'NB FERIES'
    ])
    
    # Données
    for d in donnees:
        writer.writerow([
            d['matricule'],
            d['nom'],
            d['prenom'],
            d['departement'],
            d['site'],
            d['date_debut'].strftime('%d/%m/%Y'),
            d['date_fin'].strftime('%d/%m/%Y'),
            d['duree_jours'],
            d['type_absence'],
            d['feries'],
            d['nb_feries']
        ])
    
    return response


def export_xlsx(donnees, filename, date_debut, date_fin):
    """Export en XLSX"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Fill, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        return HttpResponse("Module openpyxl non installé", status=500)
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Absences"
    
    # Styles
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    ferie_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    
    # Titre
    ws.merge_cells('A1:K1')
    ws['A1'] = f"EXTRACTION DES ABSENCES - DU {date_debut.strftime('%d/%m/%Y')} AU {date_fin.strftime('%d/%m/%Y')}"
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal="center")
    
    # Date d'extraction
    ws.merge_cells('A2:K2')
    ws['A2'] = f"Extrait le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"
    ws['A2'].alignment = Alignment(horizontal="center")
    ws['A2'].font = Font(italic=True, size=10)
    
    # En-têtes (ligne 4)
    headers = [
        'MATRICULE',
        'NOM',
        'PRENOM',
        'DEPARTEMENT',
        'SITE',
        'DATE DEPART',
        'DATE FIN',
        'NB JOURS',
        'MOTIF',
        'JOURS FERIES',
        'NB FERIES'
    ]
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
    
    # Données
    for row_idx, d in enumerate(donnees, 5):
        row_data = [
            d['matricule'],
            d['nom'],
            d['prenom'],
            d['departement'],
            d['site'],
            d['date_debut'].strftime('%d/%m/%Y'),
            d['date_fin'].strftime('%d/%m/%Y'),
            d['duree_jours'],
            d['type_absence'],
            d['feries'],
            d['nb_feries']
        ]
        
        for col, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")
            
            # Colorer en jaune si contient des fériés
            if d['nb_feries'] > 0 and col in [10, 11]:
                cell.fill = ferie_fill
    
    # Ajuster les largeurs de colonnes
    column_widths = [12, 15, 15, 20, 15, 12, 12, 10, 25, 35, 10]
    for col, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Figer les en-têtes
    ws.freeze_panes = 'A5'
    
    # Créer la réponse
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    
    wb.save(response)
    return response


def export_pdf(donnees, filename, date_debut, date_fin):
    """Export en PDF"""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
    except ImportError:
        return HttpResponse("Module reportlab non installé", status=500)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1*cm,
        bottomMargin=1*cm
    )
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Style titre
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    # Titre
    title = f"EXTRACTION DES ABSENCES<br/>Du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    elements.append(Paragraph(title, title_style))
    
    # Date d'extraction
    sub_style = ParagraphStyle(
        'SubTitle',
        parent=styles['Normal'],
        fontSize=9,
        alignment=TA_CENTER,
        spaceAfter=15
    )
    elements.append(Paragraph(f"Extrait le {datetime.now().strftime('%d/%m/%Y à %H:%M')}", sub_style))
    
    # Préparer les données du tableau
    table_data = [
        ['Matricule', 'Nom', 'Prénom', 'Département', 'Date Départ', 'Date Fin', 'Jours', 'Motif', 'Fériés']
    ]
    
    for d in donnees:
        feries_court = d['feries'] if len(d['feries']) < 30 else d['feries'][:30] + '...'
        table_data.append([
            d['matricule'],
            d['nom'],
            d['prenom'],
            d['departement'][:15] if d['departement'] else '',
            d['date_debut'].strftime('%d/%m/%Y'),
            d['date_fin'].strftime('%d/%m/%Y'),
            str(d['duree_jours']),
            d['type_absence'][:20] if d['type_absence'] else '',
            feries_court if d['nb_feries'] > 0 else '-'
        ])
    
    # Créer le tableau
    col_widths = [2*cm, 2.5*cm, 2.5*cm, 3*cm, 2.5*cm, 2.5*cm, 1.5*cm, 4*cm, 5*cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Style du tableau
    table_style = TableStyle([
        # En-tête
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        
        # Corps
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (4, 1), (6, -1), 'CENTER'),  # Dates et jours centrés
        
        # Bordures
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        
        # Alternance de couleurs
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')]),
    ])
    
    # Colorer les lignes avec fériés
    for row_idx, d in enumerate(donnees, 1):
        if d['nb_feries'] > 0:
            table_style.add('BACKGROUND', (8, row_idx), (8, row_idx), colors.HexColor('#FFF2CC'))
    
    table.setStyle(table_style)
    elements.append(table)
    
    # Statistiques en bas
    elements.append(Spacer(1, 20))
    stats_text = f"Total: {len(donnees)} absences | Absences avec fériés: {sum(1 for d in donnees if d['nb_feries'] > 0)}"
    elements.append(Paragraph(stats_text, styles['Normal']))
    
    # Générer le PDF
    doc.build(elements)
    
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    
    return response


@login_required
def api_absences_extraction(request):
    """
    API JSON pour les absences avec jours fériés
    
    URL: /interim/api/extraction/
    """
    from mainapp.models import AbsenceUtilisateur
    
    # Mêmes filtres que la vue principale
    departement_id = request.GET.get('departement', '')
    site_id = request.GET.get('site', '')
    matricule = request.GET.get('matricule', '').strip()
    date_debut_str = request.GET.get('date_debut', '')
    date_fin_str = request.GET.get('date_fin', '')
    annee_filtre = request.GET.get('annee', '')
    
    today = date.today()
    annee_courante = today.year
    
    # Année
    try:
        annee_selectionnee = int(annee_filtre) if annee_filtre else annee_courante
    except ValueError:
        annee_selectionnee = annee_courante
    
    # Dates
    try:
        date_debut = datetime.strptime(date_debut_str, '%Y-%m-%d').date() if date_debut_str else date(annee_selectionnee, 1, 1)
    except ValueError:
        date_debut = date(annee_selectionnee, 1, 1)
    
    try:
        date_fin = datetime.strptime(date_fin_str, '%Y-%m-%d').date() if date_fin_str else date(annee_selectionnee, 12, 31)
    except ValueError:
        date_fin = date(annee_selectionnee, 12, 31)
    
    absences = AbsenceUtilisateur.objects.select_related(
        'utilisateur', 'utilisateur__departement', 'utilisateur__user'
    ).filter(
        Q(date_debut__lte=date_fin) & Q(date_fin__gte=date_debut)
    ).order_by('-date_debut')
    
    if departement_id:
        try:
            absences = absences.filter(utilisateur__departement_id=int(departement_id))
        except ValueError:
            pass
    
    if site_id:
        try:
            absences = absences.filter(utilisateur__site_id=int(site_id))
        except ValueError:
            pass
    
    if matricule:
        absences = absences.filter(
            Q(utilisateur__matricule__icontains=matricule) |
            Q(utilisateur__user__first_name__icontains=matricule) |
            Q(utilisateur__user__last_name__icontains=matricule)
        )
    
    data = []
    for absence in absences[:100]:  # Limiter à 100 pour l'API
        feries = get_feries_dans_periode(absence.date_debut, absence.date_fin)
        data.append({
            'id': absence.pk,
            'matricule': absence.utilisateur.matricule,
            'nom_complet': absence.utilisateur.nom_complet,
            'departement': absence.utilisateur.departement.nom if absence.utilisateur.departement else None,
            'date_debut': absence.date_debut.isoformat(),
            'date_fin': absence.date_fin.isoformat(),
            'duree_jours': absence.duree_jours,
            'type_absence': absence.type_absence,
            'feries': [{'date': f['date'].isoformat(), 'nom': f['nom']} for f in feries],
            'nb_feries': len(feries),
        })
    
    return JsonResponse({
        'absences': data,
        'count': len(data),
        'date_debut': date_debut.isoformat(),
        'date_fin': date_fin.isoformat(),
    })