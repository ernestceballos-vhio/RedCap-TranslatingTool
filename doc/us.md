# ÚS 

## 1. DESCARREGAR CSV DE TRADUCCIÓ

1. Anar al projecte de redcap que es vol traduir.
2. Anar al Multi_Language Management
3. Fer click a Export Lenguage del idioma original amb .csv



## 2. EXECUTAR SCRIPT

1. Posar el .csv deescarregta a la carpeta data/
2. Crear compte a DeepL, i agafar l'API, alhora posar l'API a un .env que settings ja té configurat per agafar-ho
3. Executar Script amb el csv i el idioma destí (ca: català, es:espanyol)


## PENJAR TRADUCCIÓ

1. Crear Idioma en el projecte de Redcap
2. Fer click a "Update Language" i penjar el .csv que hi ha a output/idioma/ i fer click a les 3 opcions
3. Esperar a Carregar i despreés comprovar manualment que s'ha penjat bé i no hi han errors.






