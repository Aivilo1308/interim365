#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import requests
from requests.auth import HTTPBasicAuth
import warnings
import re
from urllib.parse import urljoin

warnings.filterwarnings('ignore')

def print_flush(message):
    print(message)
    sys.stdout.flush()

def discover_kelio_services():
    print_flush("🔍 DÉCOUVERTE COMPLÈTE DES SERVICES KELIO")
    print_flush("=" * 60)
    
    url = "https://keliodemo-safesecur.kelio.io/open"
    auth = HTTPBasicAuth('webservices', '12345')
    
    session = requests.Session()
    session.auth = auth
    session.verify = False
    
    # 1. Essayer d'obtenir une liste des services via /services
    print_flush("ÉTAPE 1: Exploration du répertoire /services")
    print_flush("-" * 40)
    
    try:
        services_url = f"{url}/services"
        response = session.get(services_url, timeout=15)
        print_flush(f"GET {services_url}: HTTP {response.status_code}")
        
        if response.status_code == 200:
            content = response.text
            print_flush(f"Contenu reçu: {len(content)} caractères")
            
            # Chercher des liens vers des services
            # Patterns courants: href="ServiceName" ou ServiceName?wsdl
            service_patterns = [
                r'href=["\']([^"\']*Service)["\']',
                r'href=["\']([^"\']*\.wsdl)["\']',
                r'>([A-Za-z]+Service)<',
                r'([A-Za-z]+Service)\?wsdl',
                r'>([A-Za-z]+\.wsdl)<'
            ]
            
            found_services = set()
            for pattern in service_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    if 'service' in match.lower() or match.endswith('.wsdl'):
                        found_services.add(match.replace('.wsdl', ''))
            
            if found_services:
                print_flush(f"✅ Services trouvés dans le listing:")
                for service in sorted(found_services):
                    print_flush(f"   • {service}")
            else:
                print_flush("ℹ️  Aucun service détecté dans le contenu HTML")
                # Afficher un échantillon du contenu
                if len(content) < 500:
                    print_flush("Contenu complet:")
                    print_flush(content)
                else:
                    print_flush("Début du contenu:")
                    print_flush(content[:500] + "...")
    
    except Exception as e:
        print_flush(f"❌ Erreur exploration /services: {e}")
    
    print_flush("")
    
    # 2. Essayer des variantes de noms de services
    print_flush("ÉTAPE 2: Test de variantes de noms")
    print_flush("-" * 40)
    
    # Noms alternatifs basés sur différentes versions de Kelio
    alternative_names = [
        # Versions courtes
        'Employee',
        'Employees', 
        'User',
        'Users',
        'Person',
        'Personnel',
        'Staff',
        
        # Versions avec suffixes différents
        'EmployeeWS',
        'EmployeeWebService',
        'EmployeeSoap',
        'UserService',
        'PersonnelService',
        'StaffService',
        
        # Services spécialisés
        'Absence',
        'AbsenceWS',
        'Leave',
        'LeaveService',
        'TimeOff',
        
        # Services de données
        'Data',
        'DataService',
        'Export',
        'ExportService',
        'Sync',
        'SyncService',
        
        # Services Kelio spécifiques
        'KelioEmployee',
        'KelioData',
        'KelioExport',
        'KelioSync'
    ]
    
    available_services = []
    
    for service_name in alternative_names:
        try:
            wsdl_url = f"{url}/services/{service_name}?wsdl"
            response = session.head(wsdl_url, timeout=8)
            
            if response.status_code == 200:
                available_services.append(service_name)
                print_flush(f"✅ {service_name}: TROUVÉ!")
            elif response.status_code in [401, 403]:
                print_flush(f"🔐 {service_name}: Authentification requise")
            elif response.status_code != 404:
                print_flush(f"⚠️  {service_name}: HTTP {response.status_code}")
            
        except Exception as e:
            if "timeout" not in str(e).lower():
                print_flush(f"❌ {service_name}: {str(e)[:30]}")
    
    print_flush("")
    
    # 3. Essayer des endpoints différents
    print_flush("ÉTAPE 3: Test d'endpoints alternatifs")
    print_flush("-" * 40)
    
    alternative_paths = [
        'webservices/EmployeeService?wsdl',
        'soap/EmployeeService?wsdl', 
        'ws/EmployeeService?wsdl',
        'api/EmployeeService?wsdl',
        'services/employee?wsdl',
        'services/employees?wsdl',
        'EmployeeService?wsdl',  # Directement à la racine
        'employee?wsdl',
        'employees?wsdl'
    ]
    
    for path in alternative_paths:
        try:
            test_url = f"{url}/{path}"
            response = session.head(test_url, timeout=8)
            
            if response.status_code == 200:
                print_flush(f"✅ TROUVÉ: {path}")
                available_services.append(path)
            elif response.status_code in [401, 403]:
                print_flush(f"🔐 AUTH: {path}")
                
        except Exception:
            pass
    
    print_flush("")
    
    # 4. Résumé
    print_flush("RÉSUMÉ DE LA DÉCOUVERTE")
    print_flush("=" * 40)
    
    if available_services:
        print_flush(f"🎯 {len(available_services)} service(s) disponible(s):")
        for service in available_services:
            print_flush(f"   • {service}")
        
        print_flush("\n🔧 Code à utiliser dans votre configuration:")
        for service in available_services[:3]:  # Montrer les 3 premiers
            clean_name = service.replace('?wsdl', '').split('/')[-1]
            print_flush(f"'{clean_name.lower()}': {{")
            print_flush(f"    'service_name': '{clean_name}',")
            print_flush(f"    'wsdl_path': '{service}',")
            print_flush(f"    'method': 'export{clean_name}s',  # À ajuster")
            print_flush(f"}},")
    else:
        print_flush("❌ Aucun service SOAP trouvé")
        print_flush("\n💡 Suggestions:")
        print_flush("1. Vérifiez que cette version de Kelio supporte les services SOAP")
        print_flush("2. Contactez l'administrateur Kelio pour la liste des services")
        print_flush("3. Vérifiez la documentation de votre version Kelio")
        print_flush("4. Essayez avec des identifiants différents")
    
    return available_services

if __name__ == "__main__":
    discover_kelio_services()