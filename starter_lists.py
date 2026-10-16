"""Starter lists for review (v7.5).

The live department had 12 diagnoses and 8 comorbidities, which is why
"Add other" gets used for most cases. These are STARTING POINTS for the Head
of Department to read and trim, not authority: nothing here is applied until
someone with "Review typed-in names and starter lists" ticks it and presses
Apply, and every item can be left out. Spelling follows common Indian ENT
practice and ICD-10 chapter J/H/C headings loosely; it is not a coding system.

`PROC_DX` maps procedures to the diagnoses they are usually done for. It only
feeds the "suggested diagnoses" chips on the entry form, which a trainee may
ignore, and is overridden by what the department's own entries show.
"""

DIAGNOSES = [
    # ear
    "Acute Otitis Media", "Otitis Media with Effusion", "Chronic Otitis Media – Mucosal (Safe)",
    "Chronic Otitis Media – Squamosal (Unsafe)", "Cholesteatoma", "Tympanic Membrane Perforation",
    "Otosclerosis", "Sensorineural Hearing Loss", "Sudden Sensorineural Hearing Loss",
    "Conductive Hearing Loss", "Congenital Hearing Loss", "Ossicular Discontinuity",
    "Otitis Externa", "Malignant (Necrotising) Otitis Externa", "External Auditory Canal Exostosis",
    "Microtia / Congenital Aural Atresia", "Bell's Palsy", "Facial Nerve Palsy – Temporal Bone",
    "Meniere's Disease", "BPPV", "Vestibular Schwannoma", "Glomus Tumour", "Mastoiditis",
    "Temporal Bone Fracture", "Foreign Body – Ear", "Pinna Haematoma / Trauma",
    # nose and sinuses
    "Chronic Rhinosinusitis without Polyps", "Chronic Rhinosinusitis with Polyps",
    "Acute Rhinosinusitis", "Allergic Fungal Rhinosinusitis", "Invasive Fungal Rhinosinusitis (Mucormycosis)",
    "Deviated Nasal Septum", "Allergic Rhinitis", "Vasomotor Rhinitis", "Inferior Turbinate Hypertrophy",
    "Nasal Polyposis", "Antrochoanal Polyp", "Epistaxis", "Nasal Bone Fracture",
    "Septal Perforation", "Nasolacrimal Duct Obstruction", "Choanal Atresia", "Juvenile Nasopharyngeal Angiofibroma",
    "Inverted Papilloma", "Sinonasal Malignancy", "CSF Rhinorrhoea", "Pituitary / Sellar Lesion",
    "Foreign Body – Nose", "Rhinophyma / External Nasal Deformity",
    # throat, larynx, airway
    "Chronic Tonsillitis", "Recurrent Tonsillitis", "Peritonsillar Abscess", "Adenoid Hypertrophy",
    "Obstructive Sleep Apnea", "Snoring / Upper Airway Resistance", "Vocal Cord Palsy", "Vocal Cord Nodules / Polyp",
    "Laryngeal Papillomatosis", "Laryngomalacia", "Subglottic Stenosis", "Laryngeal Malignancy",
    "Laryngopharyngeal Reflux", "Acute Epiglottitis", "Upper Airway Obstruction", "Laryngeal Trauma",
    "Foreign Body – Throat / Airway", "Foreign Body – Oesophagus", "Pharyngeal Malignancy",
    "Hypopharyngeal Malignancy", "Dysphagia", "Corrosive Injury of Upper Aerodigestive Tract",
    "Retropharyngeal / Parapharyngeal Abscess", "Ludwig's Angina / Deep Neck Space Infection",
    # head and neck
    "Thyroid Nodule / Goitre", "Thyroid Malignancy", "Multinodular Goitre", "Thyroglossal Duct Cyst",
    "Branchial Cleft Cyst / Sinus", "Parotid Tumour", "Pleomorphic Adenoma", "Submandibular Gland Disease / Sialolithiasis",
    "Neck Lump – Unknown Primary", "Cervical Lymphadenopathy", "Head & Neck Malignancy",
    "Oral Cavity Malignancy", "Oropharyngeal Malignancy", "Oral Submucous Fibrosis", "Ranula",
    "Cystic Hygroma / Lymphatic Malformation", "Hemangioma / Vascular Malformation",
    "Carotid Body Tumour", "Parathyroid Adenoma",
    # skull base, trauma
    "Skull Base Lesion", "Facial Fracture – Zygomatic / Orbital", "Mandible Fracture", "Penetrating Neck Injury",
    "Post-operative Haemorrhage", "Congenital Neck Mass",
]

COMORBIDITIES = [
    "Diabetes Mellitus", "Hypertension", "Coronary Artery Disease", "Chronic Kidney Disease",
    "COPD / Asthma", "Hypothyroidism", "Hyperthyroidism", "Immunocompromised", "Obesity",
    "Epilepsy", "Bleeding / Coagulation Disorder", "On Anticoagulants / Antiplatelets",
    "Previous Stroke", "Chronic Liver Disease", "Tuberculosis (current / treated)",
    "HIV", "Hepatitis B / C", "Pregnancy", "Anaemia", "Cardiac Valvular Disease",
    "Congenital Heart Disease", "Down Syndrome / Other Syndrome", "Cerebral Palsy / Developmental Delay",
    "Prior Radiotherapy to Head & Neck", "Smoker / Tobacco Chewer", "Alcohol Use Disorder", "None",
]

# site key -> procedures that are commonly done and not in the shipped list.
PROCEDURES = {
    "ear": [
        "Tympanomastoidectomy", "Revision mastoidectomy", "Mastoid abscess drainage",
        "Atticotomy / Attico-antrostomy", "Middle ear exploration", "Canalplasty / exostosis removal",
        "Aural polypectomy", "Pinna haematoma drainage", "Lop ear / ear keloid excision",
        "Endolymphatic sac decompression", "Transtympanic steroid / gentamicin injection",
        "Lateral temporal bone resection", "Vestibular schwannoma excision (translabyrinthine)",
        "Auditory brainstem implant", "Middle ear implant (Vibrant Soundbridge)",
    ],
    "nose": [
        "Septal abscess drainage", "Septal perforation repair", "Inferior turbinate submucosal diathermy",
        "Endoscopic sphenoidotomy", "Endoscopic frontal sinusotomy (Draf I–III)", "Caldwell-Luc operation",
        "Antral washout", "Endoscopic transsphenoidal pituitary surgery", "Endoscopic medial maxillectomy",
        "Antrochoanal polyp excision", "JNA excision", "Revision FESS", "Sphenopalatine artery ligation",
        "Posterior nasal packing", "Rhinoplasty – functional", "Nasal fracture manipulation under anaesthesia",
        "Cleft lip nasal deformity correction", "Fungal debridement (rhino-orbital)",
    ],
    "throat": [
        "Coblation tonsillectomy", "Tonsillectomy – bleeding control / return to theatre",
        "Quinsy drainage", "Palatal surgery for OSA", "Tongue-base reduction", "Drug-induced sleep endoscopy",
        "Rigid bronchoscopy ± foreign body removal", "Laryngeal papilloma debulking (microdebrider / laser)",
        "Laser cordectomy", "Laryngeal cleft repair", "Laryngotracheal reconstruction",
        "Airway balloon dilatation", "Supraglottoplasty", "Percutaneous tracheostomy", "Tracheostomy – revision / decannulation",
        "Tracheo-oesophageal puncture / voice prosthesis", "Cricopharyngeal myotomy", "Pharyngeal pouch (Zenker's) surgery",
        "Dilatation of pharyngo-oesophageal stricture", "Hypopharyngeal / pharyngolaryngectomy",
        "Medialisation thyroplasty", "Botulinum toxin injection – larynx",
    ],
    "hn": [
        "Hemiglossectomy / wide excision tongue", "Composite resection (oral cavity)", "Mandibulectomy – marginal / segmental",
        "Hemimandibulectomy with reconstruction", "Free flap harvest and inset", "Pectoralis major flap",
        "Radial forearm free flap", "Fibula free flap", "Lateral neck dissection – elective",
        "Lymph node excision biopsy", "Parathyroidectomy", "Completion thyroidectomy",
        "Retrosternal goitre excision", "Excision of carotid body tumour", "Excision of cystic hygroma",
        "Ranula excision / marsupialisation", "Sialendoscopy", "Submandibular duct stone removal",
        "Parotid abscess drainage", "Facial nerve grafting / reanimation", "Tongue-tie release (frenotomy)",
        "Excision of vallecular / base-of-tongue cyst", "Tracheostomy for malignancy",
    ],
    "skull": [
        "Anterior skull base resection (craniofacial)", "Lateral skull base approach (infratemporal fossa)",
        "Petrous apicectomy", "Endoscopic optic nerve decompression", "Endoscopic CSF leak repair with graft",
    ],
    "trauma": [
        "Examination under anaesthesia – ENT", "Epistaxis – posterior packing / balloon",
        "Septal haematoma drainage", "Laceration repair – ear / nose / face", "Emergency tracheostomy",
        "Neck exploration – penetrating injury", "Button battery removal", "Fish-bone removal – oropharynx / hypopharynx",
        "Coin removal – oesophagus", "Temporal bone fracture – facial nerve exploration", "Post-tonsillectomy bleed – cautery",
    ],
}

# Procedure -> the diagnoses it is usually done for. Matched by exact name
# against the department's procedure list.
PROC_DX = {
    "Myringotomy ± grommet (ventilation tube) insertion": ["Otitis Media with Effusion", "Acute Otitis Media"],
    "Myringoplasty": ["Chronic Otitis Media – Mucosal (Safe)", "Tympanic Membrane Perforation"],
    "Tympanoplasty (Type I–V)": ["Chronic Otitis Media – Mucosal (Safe)", "Chronic Otitis Media – Squamosal (Unsafe)", "Tympanic Membrane Perforation"],
    "Mastoidectomy – cortical / simple": ["Mastoiditis", "Chronic Otitis Media – Squamosal (Unsafe)"],
    "Mastoidectomy – canal wall down (CWD)": ["Cholesteatoma", "Chronic Otitis Media – Squamosal (Unsafe)"],
    "Mastoidectomy – canal wall up (CWU)": ["Cholesteatoma", "Chronic Otitis Media – Squamosal (Unsafe)"],
    "Ossiculoplasty": ["Ossicular Discontinuity", "Chronic Otitis Media – Mucosal (Safe)"],
    "Stapedotomy / stapedectomy": ["Otosclerosis"],
    "Cochlear implantation": ["Sensorineural Hearing Loss", "Congenital Hearing Loss"],
    "Bone-anchored hearing implant (BAHA / Bonebridge)": ["Conductive Hearing Loss", "Microtia / Congenital Aural Atresia"],
    "Pinnaplasty / otoplasty": ["Microtia / Congenital Aural Atresia"],
    "Microtia / ear reconstruction": ["Microtia / Congenital Aural Atresia"],
    "Facial nerve decompression": ["Bell's Palsy", "Facial Nerve Palsy – Temporal Bone"],
    "Glomus tumour excision": ["Glomus Tumour"],
    "Septoplasty / SMR": ["Deviated Nasal Septum"],
    "FESS – Type I (limited)": ["Chronic Rhinosinusitis without Polyps", "Acute Rhinosinusitis"],
    "FESS – Type II / III (extended)": ["Chronic Rhinosinusitis with Polyps", "Chronic Rhinosinusitis without Polyps", "Allergic Fungal Rhinosinusitis"],
    "Endoscopic DCR": ["Nasolacrimal Duct Obstruction"],
    "Turbinate reduction / turbinoplasty": ["Inferior Turbinate Hypertrophy", "Allergic Rhinitis"],
    "Nasal polypectomy": ["Nasal Polyposis", "Chronic Rhinosinusitis with Polyps"],
    "Septorhinoplasty": ["Deviated Nasal Septum", "Rhinophyma / External Nasal Deformity"],
    "Choanal atresia repair": ["Choanal Atresia"],
    "Epistaxis – cautery / packing": ["Epistaxis"],
    "Epistaxis – endoscopic vessel ligation (SPA / AEA)": ["Epistaxis"],
    "Medial / partial maxillectomy": ["Sinonasal Malignancy", "Inverted Papilloma"],
    "Adenoidectomy": ["Adenoid Hypertrophy", "Otitis Media with Effusion"],
    "Endoscopic CSF rhinorrhoea repair": ["CSF Rhinorrhoea"],
    "Tonsillectomy": ["Chronic Tonsillitis", "Recurrent Tonsillitis", "Peritonsillar Abscess"],
    "Adenotonsillectomy": ["Adenoid Hypertrophy", "Recurrent Tonsillitis", "Obstructive Sleep Apnea"],
    "Uvulopalatopharyngoplasty (UPPP)": ["Obstructive Sleep Apnea", "Snoring / Upper Airway Resistance"],
    "Direct laryngoscopy ± biopsy": ["Laryngeal Malignancy", "Vocal Cord Palsy", "Laryngeal Papillomatosis"],
    "Microlaryngeal surgery (MLS)": ["Vocal Cord Nodules / Polyp", "Laryngeal Papillomatosis"],
    "Laryngeal framework surgery (thyroplasty)": ["Vocal Cord Palsy"],
    "Vocal cord injection / medialisation": ["Vocal Cord Palsy"],
    "Tracheostomy": ["Upper Airway Obstruction", "Laryngeal Malignancy", "Vocal Cord Palsy"],
    "Cricothyroidotomy": ["Upper Airway Obstruction", "Laryngeal Trauma"],
    "Total laryngectomy": ["Laryngeal Malignancy", "Hypopharyngeal Malignancy"],
    "Partial laryngectomy": ["Laryngeal Malignancy"],
    "Rigid / flexible oesophagoscopy ± FB removal": ["Foreign Body – Oesophagus", "Dysphagia"],
    "Panendoscopy": ["Head & Neck Malignancy", "Neck Lump – Unknown Primary"],
    "Hemithyroidectomy": ["Thyroid Nodule / Goitre", "Thyroid Malignancy"],
    "Total thyroidectomy": ["Multinodular Goitre", "Thyroid Malignancy"],
    "Parotidectomy – superficial": ["Pleomorphic Adenoma", "Parotid Tumour"],
    "Parotidectomy – total / radical": ["Parotid Tumour"],
    "Submandibular gland excision": ["Submandibular Gland Disease / Sialolithiasis"],
    "Neck node biopsy / excision": ["Cervical Lymphadenopathy", "Neck Lump – Unknown Primary"],
    "Neck dissection – selective": ["Head & Neck Malignancy", "Oral Cavity Malignancy"],
    "Neck dissection – modified radical / radical": ["Head & Neck Malignancy", "Oral Cavity Malignancy"],
    "Branchial cyst / sinus excision": ["Branchial Cleft Cyst / Sinus"],
    "Thyroglossal cyst excision (Sistrunk)": ["Thyroglossal Duct Cyst"],
    "Oral cavity tumour excision": ["Oral Cavity Malignancy"],
    "Flap reconstruction (pedicled / free)": ["Oral Cavity Malignancy", "Head & Neck Malignancy"],
    "Nasal bone fracture reduction": ["Nasal Bone Fracture"],
    "Foreign body removal – ear": ["Foreign Body – Ear"],
    "Foreign body removal – nose": ["Foreign Body – Nose"],
    "Foreign body removal – throat / airway": ["Foreign Body – Throat / Airway"],
    "Peritonsillar abscess drainage": ["Peritonsillar Abscess"],
    "Deep neck space abscess drainage": ["Ludwig's Angina / Deep Neck Space Infection", "Retropharyngeal / Parapharyngeal Abscess"],
}


def diff_against(cfg):
    """What this list would add to the live config. -> {diagnoses: [...],
    comorbidities: [...], procedures: {site: [...]}} (only the new items)."""
    have_dx = {s.lower() for s in (cfg.get("diagnoses") or [])}
    have_co = {s.lower() for s in (cfg.get("comorbidities") or [])}
    out = {
        "diagnoses": [d for d in DIAGNOSES if d.lower() not in have_dx],
        "comorbidities": [c for c in COMORBIDITIES if c.lower() not in have_co],
        "procedures": {},
    }
    procs = cfg.get("procedures") or {}
    for site, items in PROCEDURES.items():
        have = {s.lower() for s in (procs.get(site) or [])}
        new = [p for p in items if p.lower() not in have]
        if new:
            out["procedures"][site] = new
    return out
