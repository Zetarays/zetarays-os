#!/usr/bin/env python3
"""Genera tz_it_IT.ts (fusi orari in italiano per Calamares) da tz_en_upstream.ts.
Upstream non ha una traduzione italiana: regioni e città con nome italiano."""
import re
from xml.sax.saxutils import escape

REGIONS = {"Africa": "Africa", "America": "America", "Antarctica": "Antartide", "Arctic": "Artico",
           "Asia": "Asia", "Atlantic": "Atlantico", "Australia": "Australia", "Europe": "Europa",
           "Indian": "Oceano Indiano", "Pacific": "Pacifico"}
NAMES = {
 "Addis Ababa": "Addis Abeba", "Algiers": "Algeri", "Athens": "Atene", "Azores": "Azzorre",
 "Baghdad": "Baghdad", "Beirut": "Beirut", "Belgrade": "Belgrado", "Berlin": "Berlino",
 "Bermuda": "Bermuda", "Bratislava": "Bratislava", "Brussels": "Bruxelles", "Bucharest": "Bucarest",
 "Budapest": "Budapest", "Cairo": "Il Cairo", "Canary": "Canarie", "Cape Verde": "Capo Verde",
 "Casablanca": "Casablanca", "Chisinau": "Chișinău", "Copenhagen": "Copenaghen", "Costa Rica": "Costa Rica",
 "Damascus": "Damasco", "Dublin": "Dublino", "Easter": "Isola di Pasqua", "Faroe": "Fær Øer",
 "Fiji": "Figi", "Galapagos": "Galápagos", "Gibraltar": "Gibilterra", "Guadeloupe": "Guadalupa",
 "Havana": "L'Avana", "Helsinki": "Helsinki", "Ho Chi Minh": "Ho Chi Minh", "Hong Kong": "Hong Kong",
 "Isle of Man": "Isola di Man", "Istanbul": "Istanbul", "Jakarta": "Giacarta", "Jamaica": "Giamaica",
 "Jerusalem": "Gerusalemme", "Johannesburg": "Johannesburg", "Kiev": "Kiev", "Kuwait": "Kuwait",
 "La Paz": "La Paz", "Lisbon": "Lisbona", "Ljubljana": "Lubiana", "London": "Londra",
 "Los Angeles": "Los Angeles", "Luxembourg": "Lussemburgo", "Madeira": "Madera", "Madrid": "Madrid",
 "Maldives": "Maldive", "Malta": "Malta", "Martinique": "Martinica", "Mauritius": "Mauritius",
 "Mexico City": "Città del Messico", "Minsk": "Minsk", "Mogadishu": "Mogadiscio", "Monaco": "Monaco",
 "Moscow": "Mosca", "New York": "New York", "Nicosia": "Nicosia", "Oslo": "Oslo", "Paris": "Parigi",
 "Podgorica": "Podgorica", "Prague": "Praga", "Puerto Rico": "Porto Rico", "Qatar": "Qatar",
 "Reunion": "Riunione", "Reykjavik": "Reykjavík", "Riga": "Riga", "Riyadh": "Riad", "Rome": "Roma",
 "San Marino": "San Marino", "Santiago": "Santiago del Cile", "Sao Paulo": "San Paolo",
 "Sao Tome": "São Tomé", "Sarajevo": "Sarajevo", "Seoul": "Seul", "Shanghai": "Shanghai",
 "Singapore": "Singapore", "Skopje": "Skopje", "Sofia": "Sofia", "South Georgia": "Georgia del Sud",
 "St Barthelemy": "Saint-Barthélemy", "St Helena": "Sant'Elena", "St Johns": "St. John's",
 "St Kitts": "Saint Kitts", "St Lucia": "Santa Lucia", "St Thomas": "Saint Thomas",
 "St Vincent": "Saint Vincent", "Stockholm": "Stoccolma", "Tallinn": "Tallinn", "Tehran": "Teheran",
 "Tirane": "Tirana", "Tokyo": "Tokyo", "Tripoli": "Tripoli", "Tunis": "Tunisi", "Vatican": "Città del Vaticano",
 "Vienna": "Vienna", "Vilnius": "Vilnius", "Warsaw": "Varsavia", "Zagreb": "Zagabria", "Zurich": "Zurigo",
 "Busingen": "Büsingen", "Mariehamn": "Mariehamn", "Guernsey": "Guernsey", "Jersey": "Jersey",
 "Andorra": "Andorra", "Vaduz": "Vaduz", "Amsterdam": "Amsterdam", "Kaliningrad": "Kaliningrad",
 "Simferopol": "Sinferopoli", "Uzhgorod": "Užhorod", "Zaporozhye": "Zaporižžja", "Volgograd": "Volgograd",
 "Cayman": "Isole Cayman", "Christmas": "Isola di Natale", "Cocos": "Isole Cocos", "Comoro": "Comore",
 "Chagos": "Chagos", "Kerguelen": "Kerguelen", "Mahe": "Mahé", "Mayotte": "Mayotte",
 "Marquesas": "Marchesi", "Norfolk": "Norfolk", "Pitcairn": "Pitcairn", "Tahiti": "Tahiti",
 "Honolulu": "Honolulu", "Chicago": "Chicago", "Denver": "Denver", "Toronto": "Toronto",
 "Vancouver": "Vancouver", "Buenos Aires": "Buenos Aires", "Argentina/Buenos Aires": "Argentina/Buenos Aires",
 "Kolkata": "Calcutta", "Dubai": "Dubai", "Karachi": "Karachi", "Kabul": "Kabul", "Bangkok": "Bangkok",
 "Manila": "Manila", "Taipei": "Taipei", "Pyongyang": "Pyongyang", "Yangon": "Yangon",
 "Kathmandu": "Kathmandu", "Colombo": "Colombo", "Dhaka": "Dacca", "Tashkent": "Taškent",
 "Tbilisi": "Tbilisi", "Yerevan": "Erevan", "Baku": "Baku", "Almaty": "Almaty", "Ulaanbaatar": "Ulan Bator",
 "Sydney": "Sydney", "Melbourne": "Melbourne", "Perth": "Perth", "Auckland": "Auckland",
 "Nairobi": "Nairobi", "Lagos": "Lagos", "Kinshasa": "Kinshasa", "Khartoum": "Khartum",
 "Dakar": "Dakar", "Accra": "Accra", "Abidjan": "Abidjan", "El Aaiun": "El Aaiún",
 "Lima": "Lima", "Bogota": "Bogotá", "Caracas": "Caracas", "Montevideo": "Montevideo",
 "Asuncion": "Asunción", "Panama": "Panamá", "Guatemala": "Guatemala", "El Salvador": "El Salvador",
 "Santo Domingo": "Santo Domingo", "Port-au-Prince": "Port-au-Prince", "Nassau": "Nassau",
 "Barbados": "Barbados", "Dominica": "Dominica", "Grenada": "Grenada", "Aruba": "Aruba", "Curacao": "Curaçao",
 "Godthab": "Nuuk", "Muscat": "Mascate", "Amman": "Amman", "Aden": "Aden", "Bahrain": "Bahrein",
 "Gaza": "Gaza", "Hebron": "Hebron", "Djibouti": "Gibuti", "Asmara": "Asmara", "Tokelau": "Tokelau",
}

def main():
    s = open("tz_en_upstream.ts", encoding="utf-8").read()
    s = s.replace('language="en_US"', 'language="it_IT"')

    def repl(m):
        src, com = m.group(2), m.group(4)
        tr = (REGIONS if com == "tz_regions" else NAMES).get(src)
        if tr is None or tr == src:
            return m.group(0)
        return m.group(1) + m.group(3) + '<translation>%s</translation>' % escape(tr)

    s = re.sub(r'(<source>(.*?)</source>\s*)(<comment>(.*?)</comment>\s*)<translation type="unfinished"></translation>',
               repl, s)
    open("tz_it_IT.ts", "w", encoding="utf-8").write(s)
    print("tradotte:", s.count("<translation>"))

main()
