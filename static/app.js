(function(){
  "use strict";

  /* ============================================================
     STATE
  ============================================================ */
  var state = {
    capReady: false,
    config: null,
    user: null,
    authMode: "login",   // login | dev-login | signup | forgot
    signupRole: "resident",
    devListDraft: {},
    authError: "",
    authBusy: false,
    view: "dashboard",
    loading: false,
    wiz: null,
    myEntries: [],
    myEntriesLoaded: false,
    consultantsList: [],
    consultantsLoaded: false,
    roster: [],
    rosterLoaded: false,
    detailUser: null,
    detailEntries: [],
    devUsers: [],
    devUsersLoaded: false,
    devAllEntries: [],
    roleAssignments: [],
    roleAssignmentsLoaded: false,
    passwordResets: [],
    passwordResetsLoaded: false,
    consultantScope: null,
    capabilities: null, // {isDeveloper,isHod,isCoordinator,isHeadOfUnit,canApprove,canManageProfiles} -- from the server, alongside `user`
    showCreateUserForm: false,
    newUserRole: "resident",
    viewingEntryId: null,
    viewingHistoryEntryId: null,
    historyEdits: [],
    historyLoading: false,
    historyError: "",
    signupPendingMessage: "",
    signupRequests: [],
    signupRequestsLoaded: false,
    manageUsers: [],
    manageUsersLoaded: false,
    reminders: [],
    remindersLoaded: false,
    dismissedReminderKey: null, // session-only -- resets on next login, never persisted
    toast: "",
    // Mobile nav drawer -- session/render-only, never persisted. The old
    // mobile layout let the nav row overflow off-screen with no way to see
    // the rest of it; below the responsive breakpoint the nav is now
    // collapsed behind this toggle instead.
    mobileNavOpen: false
  };

  // Every role that logs entries and gets the resident-style logbook/
  // dashboard experience -- "PG Resident" is one of three now.
  var TRAINEE_ROLES = ["resident","senior_resident","fellow"];
  function isTraineeRole(role){ return TRAINEE_ROLES.indexOf(role)!==-1; }
  var ROLE_LABELS = { resident:"PG Resident", senior_resident:"Senior Resident", fellow:"Fellow", consultant:"Consultant", developer:"Developer" };
  function roleLabel(role){ return ROLE_LABELS[role] || role; }

  var DEFAULT_CATEGORIES = [
    { key:"ear", name:"Ear", color:"var(--cat-ear)" },
    { key:"nose", name:"Nose & Paranasal Sinus", color:"var(--cat-nose)" },
    { key:"throat", name:"Throat & Larynx", color:"var(--cat-throat)" },
    { key:"hn", name:"Head & Neck", color:"var(--cat-hn)" },
    { key:"skull", name:"Skull Base", color:"var(--cat-skull)" },
    { key:"trauma", name:"Trauma & Emergency", color:"var(--cat-trauma)" }
  ];

  var DEFAULT_PROCEDURES = {
    ear: ["Myringotomy ± grommet (ventilation tube) insertion","Myringoplasty","Tympanoplasty (Type I–V)","Mastoidectomy – cortical / simple","Mastoidectomy – canal wall down (CWD)","Mastoidectomy – canal wall up (CWU)","Ossiculoplasty","Stapedotomy / stapedectomy","Cochlear implantation","Bone-anchored hearing implant (BAHA / Bonebridge)","EUA ear + microsuction / debridement","Pinnaplasty / otoplasty","Microtia / ear reconstruction","Facial nerve decompression","Glomus tumour excision"],
    nose: ["Septoplasty / SMR","FESS – Type I (limited)","FESS – Type II / III (extended)","Endoscopic DCR","Turbinate reduction / turbinoplasty","Nasal polypectomy","Septorhinoplasty","Choanal atresia repair","Epistaxis – cautery / packing","Epistaxis – endoscopic vessel ligation (SPA / AEA)","Medial / partial maxillectomy","Orbital decompression","Adenoidectomy","Endoscopic CSF rhinorrhoea repair"],
    throat: ["Tonsillectomy","Adenotonsillectomy","Uvulopalatopharyngoplasty (UPPP)","Direct laryngoscopy ± biopsy","Microlaryngeal surgery (MLS)","Laryngeal framework surgery (thyroplasty)","Vocal cord injection / medialisation","Tracheostomy","Cricothyroidotomy","Partial laryngectomy","Total laryngectomy","Rigid / flexible oesophagoscopy ± FB removal","Panendoscopy"],
    hn: ["Hemithyroidectomy","Total thyroidectomy","Parotidectomy – superficial","Parotidectomy – total / radical","Submandibular gland excision","Neck node biopsy / excision","Neck dissection – selective","Neck dissection – modified radical / radical","Branchial cyst / sinus excision","Thyroglossal cyst excision (Sistrunk)","Oral cavity tumour excision","Flap reconstruction (pedicled / free)"],
    skull: ["Endoscopic skull base surgery","CSF leak repair (skull base)","Combined approach (ENT + Neurosurgery)"],
    trauma: ["Nasal bone fracture reduction","Zygomatic / orbital fracture repair","Mandible fracture fixation (ENT-assisted)","Foreign body removal – ear","Foreign body removal – nose","Foreign body removal – throat / airway","Peritonsillar abscess drainage","Deep neck space abscess drainage"]
  };

  var DEFAULT_ROLE_LEVELS = ["Observed only","Assisted (2nd assistant)","Assisted (1st assistant)","Performed under direct supervision","Performed under indirect supervision","Performed independently"];
  var DEFAULT_SETTINGS_OPT = ["Elective","Emergency"];
  var DEFAULT_LATERALITY_OPT = ["Right","Left","Bilateral","Not required"];
  var DEFAULT_PG_YEAR_OPT = ["JR-1","JR-2","JR-3"];
  var DEFAULT_CONSULTANT_DESIGNATIONS = ["Assistant Professor","Associate Professor","Professor"];
  var DEFAULT_DIAGNOSES = ["Chronic Otitis Media","Chronic Rhinosinusitis","Deviated Nasal Septum","Obstructive Sleep Apnea","Head & Neck Malignancy","Vocal Cord Palsy","Otosclerosis","Congenital Aural Atresia","Allergic Rhinitis","Laryngeal Papillomatosis","Cholesteatoma","Thyroid Nodule / Goitre"];
  var DEFAULT_COMORBIDITIES = ["Diabetes Mellitus","Hypertension","Coronary Artery Disease","Chronic Kidney Disease","COPD / Asthma","Hypothyroidism","Immunocompromised","None"];
  var DEFAULT_ACADEMIC_TYPES = ["CME","Journal club","Paper presentation","University"];
  var DEFAULT_OTHER_SETTINGS = ["OPD procedure","Bedside procedure","Emergency department procedure","Treatment room procedure"];
  var DEFAULT_SEX_OPT = ["Male","Female","Other"];
  var DEFAULT_SEMINAR_TYPES = ["Seminar","Lecture","Case presentation","Guest talk"];

  // Master units list: {key, fullName, shortForm, group}. Full name shown at
  // entry time, short form (bold) shown in tables and exports.
  var DEFAULT_UNITS = [
    { key:"ent1", fullName:"Oto-laryngology Unit 1 – General ENT with specialization in Skull Base Surgery & Head and Neck Surgery", shortForm:"ENT 1", group:"Oto-laryngology Units" },
    { key:"ent2", fullName:"Oto-laryngology Unit 2 – General ENT with specialization in Pediatric ENT and Cochlear Implant Unit", shortForm:"ENT 2", group:"Oto-laryngology Units" },
    { key:"ent3", fullName:"Oto-laryngology Unit 3 – General ENT, Rhinology & Anterior Skull Base Surgery", shortForm:"ENT 3", group:"Oto-laryngology Units" },
    { key:"ent4", fullName:"Oto-laryngology Unit 4 – General ENT with specialization in Otology, Neurotology & Implant Otology", shortForm:"ENT 4", group:"Oto-laryngology Units" },
    { key:"ent5", fullName:"Oto-laryngology Unit 5 – General ENT with specialization in Laryngology, Airway and Phono Surgery", shortForm:"ENT 5", group:"Oto-laryngology Units" },
    { key:"hns1", fullName:"Head and Neck Surgery Unit 1 – Head & Neck Surgery with specialization in Head & Neck Malignancies", shortForm:"HNS 1", group:"Peripheral Postings" },
    { key:"hns2", fullName:"Head and Neck Surgery Unit 2 – Head & Neck Surgery with specialization in Oral & Buccal Malignancies", shortForm:"HNS 2", group:"Peripheral Postings" },
    { key:"esur", fullName:"Endocrine Surgery", shortForm:"ESUR", group:"Peripheral Postings" },
    { key:"s1", fullName:"General Surgery Unit 1 – General Surgery with specialization in Head & Neck Surgery", shortForm:"S1", group:"Peripheral Postings" },
    { key:"ns", fullName:"Neurosurgery", shortForm:"NS", group:"Peripheral Postings" },
    { key:"ctvs", fullName:"Cardiovascular & Thoracic Surgery", shortForm:"CTVS", group:"Peripheral Postings" },
    { key:"pls", fullName:"Plastic Surgery", shortForm:"PLS", group:"Peripheral Postings" },
    { key:"omfs", fullName:"Oral & Maxillofacial Surgery", shortForm:"OMFS", group:"Peripheral Postings" },
    { key:"anaes", fullName:"Anaesthesia", shortForm:"ANAES", group:"Peripheral Postings" },
    { key:"pmed", fullName:"Pulmonary Medicine", shortForm:"PMED", group:"Peripheral Postings" },
    { key:"rt2", fullName:"Radiation Oncology Unit 2", shortForm:"RT2", group:"Peripheral Postings" },
    { key:"monc", fullName:"Medical Oncology", shortForm:"MONC", group:"Peripheral Postings" },
    { key:"rad", fullName:"Radiodiagnosis", shortForm:"RAD", group:"Peripheral Postings" },
    { key:"drp", fullName:"DRP (placeholder — details to follow)", shortForm:"DRP", group:"Peripheral Postings" }
  ];

  function defaultConfig(){
    return {
      categories: DEFAULT_CATEGORIES.map(function(c){ return {key:c.key, name:c.name, color:c.color}; }),
      procedures: JSON.parse(JSON.stringify(DEFAULT_PROCEDURES)),
      roleLevels: DEFAULT_ROLE_LEVELS.slice(),
      settings: DEFAULT_SETTINGS_OPT.slice(),
      laterality: DEFAULT_LATERALITY_OPT.slice(),
      pgYears: DEFAULT_PG_YEAR_OPT.slice(),
      units: DEFAULT_UNITS.map(function(u){ return Object.assign({}, u); }),
      diagnoses: DEFAULT_DIAGNOSES.slice(),
      comorbidities: DEFAULT_COMORBIDITIES.slice(),
      academicTypes: DEFAULT_ACADEMIC_TYPES.slice(),
      otherProcedureSettings: DEFAULT_OTHER_SETTINGS.slice(),
      sexOptions: DEFAULT_SEX_OPT.slice(),
      seminarTypes: DEFAULT_SEMINAR_TYPES.slice(),
      consultantDesignations: DEFAULT_CONSULTANT_DESIGNATIONS.slice()
    };
  }

  /* ============================================================
     UNITS: lookup + grouped <select> options. A unit is
     {key, fullName, shortForm, group}. unitInfo() also tolerates a
     legacy plain-string value (pre-schema-change data).
  ============================================================ */
  function unitInfo(key){
    if(!key) return null;
    var list = (state.config && state.config.units) || DEFAULT_UNITS;
    for(var i=0;i<list.length;i++){ if(list[i].key===key) return list[i]; }
    for(i=0;i<list.length;i++){ if(list[i].shortForm===key || list[i].fullName===key) return list[i]; }
    return { key:key, fullName:key, shortForm:key, group:"" };
  }
  function unitShort(key){ var u=unitInfo(key); return u ? u.shortForm : "—"; }
  function unitFull(key){ var u=unitInfo(key); return u ? u.fullName : "—"; }
  function unitShortHtml(key){ var u=unitInfo(key); return u ? '<b class="short-form">'+esc(u.shortForm)+'</b>' : "—"; }
  function uniqueUnitKey(base){
    var existing = (state.config.units||[]).map(function(u){ return u.key; });
    var key = base, n = 2;
    while(existing.indexOf(key) !== -1){ key = base+"-"+n; n++; }
    return key;
  }
  function unitOptions(selectedKey){
    var groups = {}, order = [];
    (state.config.units||[]).forEach(function(u){
      if(!groups[u.group]){ groups[u.group]=[]; order.push(u.group); }
      groups[u.group].push(u);
    });
    return order.map(function(g){
      return '<optgroup label="'+esc(g||"Units")+'">'+groups[g].map(function(u){
        return '<option value="'+esc(u.key)+'" '+(u.key===selectedKey?"selected":"")+'>'+esc(u.fullName)+' ('+esc(u.shortForm)+')</option>';
      }).join("")+'</optgroup>';
    }).join("");
  }
  // Grouped, alphabetized-within-group unit list for the searchable
  // single-select (unitOptions above stays a plain grouped <select> for the
  // couple of admin-only spots that never got converted -- see the "Units"
  // task's scope note). Groups keep the admin's own group order (only two
  // groups exist -- "Oto-laryngology Units" then "Peripheral Postings" --
  // and that split is itself meaningful, unlike the ~19 units inside it).
  function unitSearchOptions(){
    var groups = {}, order = [];
    (state.config.units||[]).forEach(function(u){
      if(!groups[u.group]){ groups[u.group]=[]; order.push(u.group); }
      groups[u.group].push(u);
    });
    var out = [];
    order.forEach(function(g){
      groups[g].slice().sort(function(a,b){ return String(a.fullName).localeCompare(String(b.fullName), undefined, {sensitivity:"base"}); })
        .forEach(function(u){ out.push({ value:u.key, label:u.fullName+" ("+u.shortForm+")", group:g||"Units" }); });
    });
    return out;
  }

  // Which unit a resident belonged to on a given date, from their self-logged
  // posting history [{unit, startDate, endDate|null}]. A posting with no end
  // date is open-ended (still current). If more than one posting's range
  // covers the date, the one that started most recently wins. If none
  // covers it (a gap between postings), returns "" rather than guessing.
  function unitForDate(postings, dateStr){
    if(!postings || !postings.length || !dateStr) return "";
    var inRange = postings.filter(function(p){
      return p.startDate && p.startDate<=dateStr && (!p.endDate || p.endDate>=dateStr);
    });
    if(!inRange.length) return "";
    inRange.sort(function(a,b){ return b.startDate.localeCompare(a.startDate); });
    return inRange[0].unit;
  }

  function slugify(name){
    var s = String(name||"").toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");
    return s || ("x-"+Date.now());
  }

  function catInfo(key){
    var list = (state.config && state.config.categories) || DEFAULT_CATEGORIES;
    for(var i=0;i<list.length;i++){ if(list[i].key===key) return list[i]; }
    return {key:key,name:key||"—",color:"var(--ink-soft)"};
  }

  // Hand-drawn vintage-plate-style icons (cross-hatched, single-ink line art
  // evoking classic anatomical engravings), one per site category plus one
  // per entry type. All share a 40x40 viewBox and pick up color from
  // whatever wraps them via currentColor, so they work in both themes.
  var ICONS = {
    ear: '<path d="M15 30c-5-2-8-7-8-12 0-7 6-12 13-12 6 0 11 4 11 10 0 5-4 8-8 8-3 0-5-2-5-5 0-2 2-4 4-4"/><path class="hatch" d="M12 14l3 2M11 19l3 1M12 24l3-1"/>',
    nose: '<path d="M15 9c2 6 1 11-2 15-2 3-1 6 2 7 2 1 5 0 7-2"/><circle cx="15" cy="27" r="1.4"/><path class="hatch" d="M13 23l2 1M12 27l2 1"/>',
    throat: '<path d="M13 8v6c0 2 2 4 4 4h6c2 0 4-2 4-4V8"/><path d="M14 22c2 4 4 6 6 6s4-2 6-6"/><path d="M17 17l3 3 3-3"/><path class="hatch" d="M11 30h18M13 33h14"/>',
    hn: '<path d="M22 8c4 0 7 3 7 7 0 3-1 5-3 6l1 4c3 1 5 3 5 6v3H10v-3c0-3 2-5 5-6l1-4c-2-1-3-3-3-6 0-4 3-7 7-7z"/><path class="hatch" d="M14 30h14M13 33h16"/>',
    skull: '<path d="M20 8c-6 0-10 4-10 9 0 3 1 5 3 7v4h4v-3h6v3h4v-4c2-2 3-4 3-7 0-5-4-9-10-9z"/><circle cx="16" cy="17" r="1.5"/><circle cx="24" cy="17" r="1.5"/><path d="M18 23h4"/><path class="hatch" d="M13 15l2 1M27 15l-2 1"/>',
    trauma: '<path d="M20 6l11 4v9c0 8-5 13-11 15-6-2-11-7-11-15v-9z"/><path d="M20 15v10M15 20h10"/>',
    surgical: '<path d="M8 32l14-14"/><path d="M22 18l6-6c1-1 3-1 4 0 1 1 1 3 0 4l-6 6-4-4z"/>',
    other: '<path d="M12 8v8c0 4 3 7 7 7s7-3 7-7V8"/><path d="M19 23v4c0 3 2 5 5 5s5-2 5-5v-2"/><circle cx="29" cy="30" r="2.2"/><path class="hatch" d="M8 8h4M16 8h4"/>',
    "case": '<path d="M9 8h14v20H9z"/><path class="hatch" d="M12 13h8M12 17h8M12 21h5"/><circle cx="26" cy="26" r="5"/><path d="M30 30l4 4"/>',
    academic: '<path d="M20 8l16 7-16 7-16-7z"/><path d="M12 18v7c0 2 4 4 8 4s8-2 8-4v-7"/><path class="hatch" d="M36 15v9"/>',
    seminar: '<path d="M8 34V16h10l6-6v24"/><path class="hatch" d="M24 14h10M24 20h10M24 26h6"/>',
    menu: '<path d="M8 12h24M8 20h24M8 28h24"/>',
    close: '<path d="M11 11l18 18M29 11L11 29"/>',
    users: '<circle cx="15" cy="14" r="5"/><path d="M6 33c0-6 4-10 9-10s9 4 9 10"/><circle cx="28" cy="16" r="4"/><path d="M22 33c0-5 3-8 6-8s6 3 6 8" class="hatch"/>',
    approvals: '<path d="M9 20l7 7 15-15"/><circle cx="20" cy="20" r="15"/>',
    password: '<rect x="10" y="18" width="20" height="14" rx="2"/><path d="M14 18v-4c0-3 3-6 6-6s6 3 6 6v4"/><circle cx="20" cy="24" r="2" class="hatch"/>',
    units: '<path d="M8 32V14l12-6 12 6v18"/><path class="hatch" d="M14 32v-8h5v8M21 32v-8h5v8M13 18h14"/>',
    lists: '<path d="M11 9h18M11 9v22h18V9" />' + '<path class="hatch" d="M15 15h10M15 20h10M15 25h6"/>',
    "export": '<path d="M20 6v18M14 18l6 6 6-6"/><path d="M8 28v6h24v-6" class="hatch"/>'
  };
  function icon(key, extraClass){
    var body = ICONS[key];
    if(!body) return "";
    return '<svg class="icon icon-hatch'+(extraClass?" "+extraClass:"")+'" viewBox="0 0 40 40" aria-hidden="true">'+body+'</svg>';
  }

  /* ---------- backward-compat readers for entries logged under the
     earlier 2-type (procedure/case) schema, so old data keeps
     displaying correctly instead of silently disappearing. ---------- */
  function normType(e){ return e.entryType==="procedure" ? "surgical" : e.entryType; }

  // A Surgical/Other Procedure entry can now cover more than one site in the
  // same sitting (e.g. a combined Ear+Nose case), each with its own
  // procedures, laterality and entrustment level -- see procedureBlocks.
  // entrySite/entryProcedures below stay as the single-value/flat readers
  // every other entry type (and older display code) already expects; for a
  // surgical/other entry they now return the FIRST block's site and the
  // UNION of every block's procedures respectively -- fine for a plain list
  // or search, but never sufficient on its own to describe a multi-block
  // entry, which is why summarizeEntry/entryRoleSummary/the detail modal
  // read entryProcedureBlocks directly instead of these two.
  function entryProcedureBlocks(e){
    if(e.procedureBlocks && e.procedureBlocks.length) return e.procedureBlocks;
    // Backward compat: an entry from before this feature (or the backend's
    // one-time migration hasn't run yet against it for some reason) still
    // carries its site/procedures/laterality/role as flat fields -- treat
    // that as an equivalent single block rather than showing nothing.
    if(e.site || (e.procedures && e.procedures.length) || e.procedure){
      return [{ site: e.site||e.category||"", procedures: entryProceduresFlat(e), laterality: e.laterality||"", role: e.role||"" }];
    }
    return [];
  }
  function entryProceduresFlat(e){
    if(e.procedures && e.procedures.length) return e.procedures;
    return e.procedure ? [e.procedure] : [];
  }
  function entrySite(e){
    var blocks = entryProcedureBlocks(e);
    return blocks.length ? (blocks[0].site||"") : "";
  }
  function entryProcedures(e){
    var blocks = entryProcedureBlocks(e);
    if(!blocks.length) return entryProceduresFlat(e);
    var out = [];
    blocks.forEach(function(b){ (b.procedures||[]).forEach(function(p){ out.push(p); }); });
    return out;
  }
  // One row per site touched, "Site — Procedures (Laterality, Role)" -- used
  // wherever a full per-block breakdown belongs (detail modal, edit-history
  // formatting), as opposed to entrySite/entryProcedures' flattened view.
  function entryRoleSummary(e){
    var blocks = entryProcedureBlocks(e);
    if(!blocks.length) return e.role||"";
    var roles = blocks.map(function(b){ return b.role||""; }).filter(Boolean);
    var uniq = roles.filter(function(v,i,a){ return a.indexOf(v)===i; });
    if(uniq.length<=1) return uniq[0]||"";
    return blocks.map(function(b){ return catInfo(b.site).name+": "+(b.role||"—"); }).join("; ");
  }
  // "Diagnosis" was renamed "Primary Diagnosis" in the UI; the stored field
  // key stays `diagnoses` for backward compatibility with entries logged
  // before the rename. `diagnosesSecondary` is a newer, always-optional field
  // that simply may not exist on older entries.
  function entryDiagnoses(e){
    if(e.diagnoses && e.diagnoses.length) return e.diagnoses;
    return e.diagnosis ? [e.diagnosis] : [];
  }
  function entrySecondaryDiagnoses(e){ return e.diagnosesSecondary || []; }
  function entryComorbidities(e){ return e.comorbidities || []; }
  function entryHospitalNumber(e){ return e.hospitalNumber || e.uhid || ""; }
  function entryAgeSex(e){
    var age = e.age; var sex = e.sex;
    if(!age && !sex) return "—";
    return (age||"—") + "/" + (sex||"—");
  }
  function entryConsultantAndAssistants(e){
    var c = e.consultant || "";
    var a = e.assistants || "";
    if(!c && !a) return "—";
    if(!a) return esc(c);
    return esc(c) + (c?' <span class="muted">+ '+esc(a)+'</span>' : esc(a));
  }

  function summarizeEntry(e){
    var t = normType(e);
    if(t==="surgical" || t==="other"){
      var blocks = entryProcedureBlocks(e);
      if(blocks.length<=1){
        var b = blocks[0]||{};
        return catInfo(b.site||"").name + " — " + ((b.procedures||[]).join(", ") || "—");
      }
      // A combined multi-site case: "Ear (Septoplasty); Nose (FESS)" rather
      // than the single "Site — Procedures" format, which has nowhere to
      // put a second site.
      return blocks.map(function(b){ return catInfo(b.site).name+" ("+((b.procedures||[]).join(", ")||"—")+")"; }).join("; ");
    }
    if(t==="case"){ return entryDiagnoses(e).join(", ") || "Interesting case"; }
    if(t==="academic"){ return (e.academicType==="Other" ? e.academicTypeOther : e.academicType) || "Academic activity"; }
    if(t==="seminar"){ return ((e.seminarType==="Other"?e.seminarTypeOther:e.seminarType)||"Seminar") + (e.topic ? " — "+e.topic : ""); }
    return "—";
  }
  var ENTRY_TYPE_CHIP = { surgical:["chip-teal","Surgical procedure"], other:["chip-amber","Other procedure"], case:["chip-grey","Interesting case"], academic:["chip-green","Academic"], seminar:["chip-violet","Seminar/Presentation"] };
  function entryTypeChip(e){
    var m = ENTRY_TYPE_CHIP[normType(e)] || ["chip-grey", e.entryType];
    return '<span class="chip '+m[0]+'">'+esc(m[1])+'</span>';
  }
  // Find the Interesting Case entry a surgical entry's case-report was
  // chained into (set via linkedFromId when that case entry was created).
  function findLinkedCase(surgicalEntryId, allEntries){
    return allEntries.filter(function(x){ return x.linkedFromId===surgicalEntryId; })[0] || null;
  }
  function findEntryById(id){
    // id may arrive as a string (every DOM data-* attribute reads back as a
    // string) while entry.id is a number straight from the JSON API --
    // compare loosely (==) so a string "12" still matches the number 12.
    var pools = [state.myEntries||[], state.detailEntries||[], state.devAllEntries||[]];
    for(var i=0;i<pools.length;i++){
      var hit = pools[i].filter(function(x){ return x.id==id; })[0];
      if(hit) return hit;
    }
    return null;
  }

  /* ============================================================
     UTIL
  ============================================================ */
  function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]; }); }
  function el(id){ return document.getElementById(id); }
  function todayISO(){ var d=new Date(); return d.toISOString().slice(0,10); }
  function fmtDate(s){ if(!s) return "—"; try{ var d=new Date(s+"T00:00:00"); return d.toLocaleDateString(undefined,{day:"2-digit",month:"short",year:"numeric"}); }catch(e){ return s; } }
  function fmtDateTime(s){ if(!s) return "—"; try{ var d=new Date(s); return d.toLocaleString(undefined,{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}); }catch(e){ return s; } }
  function cleanUsername(u){ return String(u||"").trim().toLowerCase().replace(/[^a-z0-9._-]/g,""); }

  function toast(msg){ state.toast = msg; render(); setTimeout(function(){ if(state.toast===msg){ state.toast=""; render(); } }, 3200); }

  /* ============================================================
     API LAYER - every call goes to the real Flask/SQLite backend
     over fetch(). Session auth is an httpOnly cookie the browser
     sends automatically; nothing here ever touches a password
     hash -- plaintext travels once, over HTTPS, straight to the
     server, which hashes it immediately (see backend/auth.py).
  ============================================================ */
  async function api(method, path, body){
    var opts = { method: method, headers:{}, credentials:"same-origin" };
    if(body!==undefined){ opts.headers["Content-Type"]="application/json"; opts.body=JSON.stringify(body); }
    var res = await fetch("/api"+path, opts);
    var data = null;
    try{ data = await res.json(); }catch(e){ data = null; }
    if(!res.ok){ throw new Error((data && data.error) || ("Request failed ("+res.status+")")); }
    return data;
  }

  async function dGetUser(username){
    try{ return (await api("GET","/users/"+encodeURIComponent(username))).user; }
    catch(e){ return null; }
  }
  async function dCreateUser(username, data){
    await api("POST","/users",{ username:username, password:data.password, role:data.role, displayName:data.displayName, pgYear:data.pgYear, designation:data.designation, unit:data.unit });
  }
  async function dUpdateUser(username, patch){ await api("PATCH","/users/"+encodeURIComponent(username), patch); }
  async function dDeleteUser(username){ await api("DELETE","/users/"+encodeURIComponent(username)); }
  async function dListUsers(){ return (await api("GET","/users")).users; }
  async function dListSignupRequests(){ return (await api("GET","/signup-requests")).requests; }
  async function dApproveSignup(username){ await api("POST","/signup-requests/"+encodeURIComponent(username)+"/approve"); }
  async function dRejectSignup(username){ await api("POST","/signup-requests/"+encodeURIComponent(username)+"/reject"); }
  async function dAddEntry(data){ return (await api("POST","/entries", data)).entry.id; }
  async function dUpdateEntry(id, data){ return (await api("PATCH","/entries/"+id, data)).entry; }
  async function dDeleteEntry(id){ await api("DELETE","/entries/"+id); }
  async function dListEntriesByAuthor(username){
    var path = username===state.user.username ? "/entries/mine" : "/entries/by-author/"+encodeURIComponent(username);
    return (await api("GET", path)).entries;
  }
  async function dListAllEntries(){ return (await api("GET","/entries/all")).entries; }
  async function dGetReminders(){ return (await api("GET","/reminders")).reminders; }
  async function dGetEntryHistory(id){ return (await api("GET","/entries/"+id+"/history")).edits; }
  async function dGetConfig(){ return (await api("GET","/config")).config; }
  async function dUpdateConfig(patch){ return (await api("PATCH","/config", patch)).config; }
  async function dListRoleAssignments(){ return (await api("GET","/role-assignments")).roleAssignments; }
  async function dAddRoleAssignment(data){ return (await api("POST","/role-assignments",{
    consultantUsername:data.consultantUsername, role:data.role, unit:data.unit, startAt:data.startAt, endAt:data.endAt
  })).roleAssignment.id; }
  async function dRemoveRoleAssignment(id){ await api("DELETE","/role-assignments/"+id); }
  async function dListPasswordRequests(){ return (await api("GET","/password-requests")).requests; }
  async function dResolvePasswordRequest(id){ await api("POST","/password-requests/"+id+"/resolve"); }

  /* ============================================================
     BOOT
  ============================================================ */
  async function boot(){
    render();
    try{ state.config = await dGetConfig(); }catch(e){ state.config = defaultConfig(); }
    state.capReady = true;

    try{
      var me = await api("GET","/auth/me");
      if(me.user){
        state.user = me.user;
        state.capabilities = me.capabilities;
        state.view = defaultViewFor(me.user.role);
        try{ state.user.postings = (await api("GET","/postings")).postings; }catch(e){ state.user.postings = []; }
      }
    }catch(e){}
    render();
    if(state.user) loadForView();
  }

  function defaultViewFor(role){ return "dashboard"; }

  /* ============================================================
     AUTH ACTIONS
  ============================================================ */
  async function doLogin(username, password, requireRole){
    state.authError=""; state.authBusy=true; render();
    try{
      var res = await api("POST","/auth/login",{ username: cleanUsername(username), password: password, requireRole: requireRole });
      state.user = res.user;
      state.capabilities = res.capabilities;
      try{ state.user.postings = (await api("GET","/postings")).postings; }catch(e){ state.user.postings = []; }
      state.view = defaultViewFor(res.user.role);
      state.authBusy=false;
      render();
      loadForView();
    }catch(err){
      state.authError = err.message || "Something went wrong signing in. Please try again.";
      state.authBusy=false; render();
    }
  }

  async function doSignup(fields){
    state.authError=""; state.authBusy=true; render();
    try{
      if((fields.username||"").length < 3){ state.authError="Username must be at least 3 characters (letters, numbers, . _ -)."; state.authBusy=false; render(); return; }
      if((fields.password||"").length < 8){ state.authError="Password must be at least 8 characters."; state.authBusy=false; render(); return; }
      if(fields.password !== fields.confirm){ state.authError="Passwords do not match."; state.authBusy=false; render(); return; }
      var res = await api("POST","/auth/signup",{
        username: cleanUsername(fields.username), password: fields.password, confirm: fields.confirm,
        displayName: fields.displayName, role: fields.role, pgYear: fields.pgYear,
        designation: fields.designation, unit: fields.unit
      });
      if(res.pending){
        state.authBusy=false;
        state.authMode = "signup-pending";
        state.signupPendingMessage = res.message || "Your account is awaiting approval.";
        render();
        return;
      }
      state.user = res.user;
      state.capabilities = res.capabilities;
      state.user.postings = [];
      state.view = defaultViewFor(res.user.role);
      state.authBusy=false;
      render();
      if(res.firstUser){ toast("You're the first account on this log — you've been made Developer/Admin."); }
      loadForView();
    }catch(err){
      state.authError = err.message || "Something went wrong creating the account. Please try again.";
      state.authBusy=false; render();
    }
  }

  async function submitForgotPassword(username, note){
    state.authError=""; state.authBusy=true; render();
    try{
      if((username||"").trim().length < 3){ state.authError="Enter your username first."; state.authBusy=false; render(); return; }
      await api("POST","/auth/forgot-password",{ username: cleanUsername(username), note: (note||"").trim() });
      state.authBusy=false;
      state.authMode = "login";
      state.authError = "";
      render();
      toast("Request sent — your Developer admin will set a new password.");
    }catch(e){
      state.authError = e.message || "Could not submit the request. Please try again.";
      state.authBusy=false; render();
    }
  }

  function doLogout(){
    api("POST","/auth/logout").catch(function(){});
    state.user = null;
    state.capabilities = null;
    state.authMode = "login";
    state.myEntriesLoaded=false; state.rosterLoaded=false; state.devUsersLoaded=false; state.detailUser=null;
    state.passwordResetsLoaded=false; state.consultantsLoaded=false;
    state.signupRequestsLoaded=false; state.signupRequests=[]; state.manageUsersLoaded=false; state.manageUsers=[];
    state.remindersLoaded=false; state.reminders=[]; state.dismissedReminderKey=null;
    render();
  }

  async function changeOwnPassword(oldPw, newPw, confirmPw){
    if(!newPw || newPw.length < 8){ toast("New password must be at least 8 characters."); return; }
    if(newPw !== confirmPw){ toast("New passwords do not match."); return; }
    try{
      await api("POST","/auth/change-password",{ oldPassword: oldPw, newPassword: newPw, confirm: confirmPw });
      toast("Password updated.");
      render();
    }catch(e){ toast(e.message || "Could not update password."); }
  }

  /* ============================================================
     DATA LOADING PER VIEW
  ============================================================ */
  async function loadMyEntries(){
    state.loading = !state.myEntriesLoaded; render();
    try{ state.myEntries = await dListEntriesByAuthor(state.user.username); }catch(e){}
    state.myEntriesLoaded = true; state.loading=false;
  }
  async function loadConsultants(){
    if(state.consultantsLoaded) return;
    try{ state.consultantsList = (await api("GET","/users/consultants")).users; }catch(e){}
    state.consultantsLoaded = true;
  }
  async function loadReminders(){
    try{ state.reminders = await dGetReminders(); }catch(e){ state.reminders = []; }
    state.remindersLoaded = true;
  }
  async function loadRoster(){
    state.loading = !state.rosterLoaded; render();
    try{
      var res = await api("GET","/entries/roster");
      state.roster = res.roster;
      state.consultantScope = res.scope;
    }catch(e){}
    state.rosterLoaded = true; state.loading=false;
  }
  async function loadDevUsers(){
    state.loading = !state.devUsersLoaded; render();
    try{ state.devUsers = await dListUsers(); }catch(e){}
    state.devUsersLoaded = true; state.loading=false;
  }
  async function loadDevEntries(){
    try{ state.devAllEntries = await dListAllEntries(); }catch(e){}
  }
  async function loadRoleAssignments(){
    try{ state.roleAssignments = await dListRoleAssignments(); }catch(e){}
    state.roleAssignmentsLoaded = true;
  }
  async function loadPasswordRequests(){
    try{ state.passwordResets = await dListPasswordRequests(); }catch(e){}
    state.passwordResetsLoaded = true;
  }
  async function loadSignupRequests(){
    try{ state.signupRequests = await dListSignupRequests(); }catch(e){}
    state.signupRequestsLoaded = true;
  }
  async function loadManageUsers(){
    try{ state.manageUsers = await dListUsers(); }catch(e){}
    state.manageUsersLoaded = true;
  }

  async function loadForView(){
    if(!state.user) return;
    var v = state.view, role = state.user.role, caps = state.capabilities || {};
    if(v==="dashboard"){
      state.loading = true; render();
      if(isTraineeRole(role)){ await loadMyEntries(); await loadReminders(); }
      else if(role==="consultant"){
        await loadRoster();
        if(caps.canApprove){ await loadSignupRequests(); }
      }
      else { await loadDevUsers(); await loadDevEntries(); await loadPasswordRequests(); await loadSignupRequests(); }
      state.loading=false; render(); return;
    }
    if(v==="resident-log"){ await loadConsultants(); render(); return; }
    if(v==="resident-entries" || v==="resident-progress"){ await loadMyEntries(); render(); return; }
    if(v==="consultant-roster"){ await loadRoster(); render(); return; }
    if(v==="developer-users"){ await loadDevUsers(); render(); return; }
    if(v==="developer-roles"){ state.loading=!state.roleAssignmentsLoaded; render(); await loadDevUsers(); await loadRoleAssignments(); state.loading=false; render(); return; }
    if(v==="developer-data"){ state.loading=true; render(); await loadDevUsers(); await loadDevEntries(); state.loading=false; render(); return; }
    if(v==="developer-password-requests"){ state.loading=!state.passwordResetsLoaded; render(); await loadDevUsers(); await loadPasswordRequests(); state.loading=false; render(); return; }
    if(v==="signup-approvals"){ state.loading=!state.signupRequestsLoaded; render(); await loadSignupRequests(); state.loading=false; render(); return; }
    if(v==="manage-users"){ state.loading=!state.manageUsersLoaded; render(); await loadManageUsers(); state.loading=false; render(); return; }
  }

  async function openResidentDetail(username){
    state.detailUser = null; state.detailEntries=[];
    state.view = "consultant-detail";
    render();
    try{
      var found = state.roster.filter(function(r){ return r.user.username===username; })[0];
      if(found){ state.detailUser = found.user; state.detailEntries = found.entries; }
      else {
        state.detailUser = await dGetUser(username);
        state.detailEntries = await dListEntriesByAuthor(username);
      }
    }catch(e){}
    render();
  }

  /* ============================================================
     RESIDENT POSTINGS (unit + start/end date)
  ============================================================ */
  async function addPosting(unit, startDate, endDate){
    if(!unit){ toast("Pick a unit."); return; }
    if(!startDate){ toast("Pick a start date."); return; }
    if(endDate && endDate < startDate){ toast("End date can't be before the start date."); return; }
    try{
      var res = await api("POST","/postings",{ unit:unit, startDate:startDate, endDate: endDate||null });
      state.user.postings = res.postings;
      toast("Posting added.");
      render();
    }catch(e){ toast(e.message || "Could not save this posting."); }
  }
  async function removePosting(idx){
    if(!confirm("Remove this posting?")) return;
    var posting = (state.user.postings||[])[idx];
    if(!posting) return;
    try{
      var res = await api("DELETE","/postings/"+posting.id);
      state.user.postings = res.postings;
      render();
    }catch(e){ toast(e.message || "Could not remove this posting."); }
  }

  /* ============================================================
     ENTRY WIZARD - four single-step forms (Surgical Procedure,
     Other Procedure, Interesting Case, Academic Participation).
     All field state lives in state.wiz.fields regardless of type.
  ============================================================ */
  function startWizard(type, prefill){
    var fields = { date: todayISO() };
    if(type==="surgical"){
      Object.assign(fields, { procedureBlocks:[newProcedureBlock([])], setting:state.config.settings[0], hospitalNumber:"", age:"", sex:state.config.sexOptions[0], diagnoses:[], diagnosesSecondary:[], comorbidities:[], consultantChoice:"__other__", consultant:"", assistantsPicked:[], comments:"", caseReport:"No" });
    } else if(type==="other"){
      Object.assign(fields, { otherSettingType:state.config.otherProcedureSettings[0], procedureBlocks:[newProcedureBlock([])], setting:state.config.settings[0], hospitalNumber:"", age:"", sex:state.config.sexOptions[0], diagnoses:[], diagnosesSecondary:[], comorbidities:[], consultantChoice:"__other__", consultant:"", assistantsPicked:[], comments:"" });
    } else if(type==="case"){
      Object.assign(fields, { hospitalNumber:"", age:"", sex:state.config.sexOptions[0], diagnoses:[], diagnosesSecondary:[], comorbidities:[], procedures:[], history:"", examination:"", comments:"" });
    } else if(type==="academic"){
      Object.assign(fields, { academicType:state.config.academicTypes[0], academicTypeOther:"", details:"" });
    } else if(type==="seminar"){
      Object.assign(fields, { seminarType:state.config.seminarTypes[0], seminarTypeOther:"", topic:"", venue:"", details:"" });
    }
    if(prefill) Object.assign(fields, prefill);
    state.wiz = { entryType:type, fields:fields, linkedFromId:(prefill&&prefill.linkedFromId)||null, editingId:null, linkedCaseId:null, origSnapshot:null, peopleList:[], peopleUnit:null };
    render();
    if(type==="surgical" || type==="other") loadWizPeopleList();
  }
  // Unit+date-scoped Consultant/Assistants picker: re-fetched whenever the
  // wizard's resolved unit or date changes, with a graceful fallback to the
  // existing org-wide consultants list when no unit can be resolved for the
  // chosen date at all (e.g. no posting covers it yet).
  async function loadWizPeopleList(){
    if(!state.wiz) return;
    var f = state.wiz.fields;
    var unit = unitForDate(state.user.postings, f.date);
    state.wiz.peopleUnit = unit;
    if(unit){
      try{
        var res = await api("GET","/units/"+encodeURIComponent(unit)+"/people?date="+encodeURIComponent(f.date));
        state.wiz.peopleList = res.people || [];
      }catch(e){ state.wiz.peopleList = []; }
    } else {
      state.wiz.peopleList = (state.consultantsList||[]).map(function(c){ return { username:c.username, displayName:c.displayName, role:"consultant" }; });
    }
    render();
  }
  function wizConsultantOptions(){
    var f = state.wiz.fields;
    var scoped = (state.wiz.peopleList||[]).filter(function(p){ return p.role==="consultant"; });
    // Never let the dropdown silently drift away from an already-chosen
    // consultant just because they're not in the current unit/date scope
    // (editing an older entry, or the posting/date changed since) -- keep
    // them selectable, clearly marked, rather than letting the browser fall
    // back to whichever option happens to render first.
    if(f.consultantChoice && f.consultantChoice!=="__other__" && !scoped.some(function(p){ return p.username===f.consultantChoice; })){
      var known = (state.consultantsList||[]).filter(function(c){ return c.username===f.consultantChoice; })[0];
      if(known) scoped = scoped.concat([{ username:known.username, displayName:known.displayName+" (not in this unit)", role:"consultant" }]);
    }
    return scoped;
  }
  function wizPeopleDisplayNames(){
    return (state.wiz.peopleList||[]).map(function(p){ return p.displayName; });
  }
  function cancelWizard(){ state.wiz=null; render(); }

  // Re-opens the wizard pre-filled from an existing entry, in edit mode
  // (state.wiz.editingId set) so the submitX() functions PATCH instead of
  // creating a new row. Field names already match 1:1 with the wizard's
  // `fields` shape (both came from the same camelCase convention) except
  // `consultantChoice`, which the dropdown needs derived from consultantUsername.
  //
  // For a surgical entry specifically, also remember (a) whether it already
  // has a linked Interesting Case entry (so submitSurgical can offer to sync
  // edits into it) and (b) a snapshot of the fields that case entry actually
  // shares with this one, so that offer only fires when something shared
  // really changed.
  async function editEntry(id){
    var e = findEntryById(id);
    if(!e) return;
    await loadConsultants(); // normally loaded on the way into "Log Entry"; edit jumps straight to the form
    var type = normType(e);
    var fields = Object.assign({}, e);
    fields.consultantChoice = e.consultantUsername || "__other__";
    // The Assistants column stays a plain comma-joined TEXT string in the
    // database (no schema change) -- back-parse it into the picker's array
    // shape here. Any name that isn't in the current unit/date-scoped list
    // (a peripheral assistant, someone who's since left, or just a stale
    // roster) still shows up as a removable "extra" chip via multiPicker's
    // existing built-in handling for values outside its options list.
    if(type==="surgical" || type==="other"){
      fields.assistantsPicked = (e.assistants||"").split(",").map(function(s){ return s.trim(); }).filter(Boolean);
      // Fresh copies of every block (and its procedures array) -- the
      // wizard mutates blocks in place (wizSetBlockSite, __entlog_setBlockField,
      // the procedures multiPicker), which must never reach back into the
      // cached entry sitting in state.myEntries/state.roster before submit.
      fields.procedureBlocks = entryProcedureBlocks(e).map(function(b){
        return { site:b.site||"", procedures:(b.procedures||[]).slice(), laterality:b.laterality||"", role:b.role||"" };
      });
      if(!fields.procedureBlocks.length) fields.procedureBlocks = [newProcedureBlock([])];
    }
    startWizard(type, fields);
    state.wiz.editingId = id;
    if(type==="surgical"){
      var linked = findLinkedCase(e.id, state.myEntries||[]);
      state.wiz.linkedCaseId = linked ? linked.id : null;
      state.wiz.origSnapshot = {
        hospitalNumber: e.hospitalNumber||"", age: e.age||"", sex: e.sex||"",
        diagnoses: (e.diagnoses||[]).slice(), diagnosesSecondary: (e.diagnosesSecondary||[]).slice(),
        comorbidities: (e.comorbidities||[]).slice(), procedures: entryProcedures(e).slice()
      };
    }
    state.view = "resident-log";
    render();
  }

  // Shallow "did anything the Interesting Case would care about actually
  // change" check, used to decide whether editing a linked surgical entry
  // should prompt to sync those changes into the case -- order-insensitive
  // for the multi-select fields so re-ticking the same set in a different
  // order doesn't trigger a needless prompt.
  function arraysEqualLoose(a,b){
    a = (a||[]).slice().sort(); b = (b||[]).slice().sort();
    if(a.length!==b.length) return false;
    for(var i=0;i<a.length;i++){ if(a[i]!==b[i]) return false; }
    return true;
  }
  function sharedCaseFieldsChanged(a,b){
    if((a.hospitalNumber||"")!==(b.hospitalNumber||"")) return true;
    if((a.age||"")!==(b.age||"")) return true;
    if((a.sex||"")!==(b.sex||"")) return true;
    if(!arraysEqualLoose(a.diagnoses,b.diagnoses)) return true;
    if(!arraysEqualLoose(a.diagnosesSecondary,b.diagnosesSecondary)) return true;
    if(!arraysEqualLoose(a.comorbidities,b.comorbidities)) return true;
    if(!arraysEqualLoose(a.procedures,b.procedures)) return true;
    return false;
  }

  // Pushes the shared clinical fields from a just-edited surgical entry into
  // its linked Interesting Case entry. The case entry's own fields (date,
  // history, examination, comments) are left exactly as they are -- only the
  // fields the two forms actually have in common are overwritten. Because
  // the PATCH endpoint replaces every column on the row, the case's own
  // values for those other fields must be sent back unchanged rather than
  // omitted, or they'd be wiped to blank.
  async function applyCaseSync(caseId, source){
    var caseEntry = findEntryById(caseId);
    if(!caseEntry) return;
    var patch = {
      entryType: "case", date: caseEntry.date,
      hospitalNumber: source.hospitalNumber, age: source.age, sex: source.sex,
      diagnoses: source.diagnoses, diagnosesSecondary: source.diagnosesSecondary||[],
      comorbidities: source.comorbidities, procedures: source.procedures,
      history: caseEntry.history, examination: caseEntry.examination,
      comments: caseEntry.comments, linkedFromId: caseEntry.linkedFromId
    };
    try{
      await dUpdateEntry(caseId, patch);
      state.myEntriesLoaded = false;
      toast("Linked Interesting Case updated to match.");
      render();
      await loadForView();
    }catch(err){ toast("Could not update the linked Interesting Case."); }
  }

  // Multi-select-with-free-text-add: shared mutation helpers used by every
  // checkbox/add-button wired in wireShellEvents for a state.wiz.fields[key] array.
  // The wizard forms read several fields (hospital number, setting, laterality,
  // role, assistants, comments, case-report toggle, free-text notes, etc.)
  // straight off the live DOM at submit time rather than keeping them in
  // state.wiz.fields on every keystroke. That's fine right up until something
  // else forces a re-render of the form (picking a diagnosis/procedure
  // checkbox, changing site) -- render() rebuilds those inputs from
  // state.wiz.fields, and anything the user typed that was never copied back
  // into state would otherwise be silently wiped. Snapshot the live values
  // into state immediately before any such re-render so nothing is lost.
  function syncWizFieldsFromDom(){
    if(!state.wiz) return;
    var f = state.wiz.fields;
    // f-assistants is no longer a plain input (it's the unit-scoped
    // multiPicker "assistantsPicked" array, kept live in state.wiz.fields by
    // mpToggle/mpAddExtra/mpRemoveExtra directly -- same as diagnoses,
    // procedures and comorbidities, none of which are in this DOM-sync list
    // either), so it's deliberately absent here.
    // f-laterality/f-role no longer exist as top-level ids -- a Surgical/
    // Other Procedure block's own laterality/role selects commit
    // immediately via their onchange (__entlog_setBlockField), the same
    // "immediate commit, no DOM-scrape needed" treatment site already got.
    var ids = ["f-hospitalNumber","f-date","f-setting",
      "f-comments","f-caseReport","f-otherSettingType","f-history","f-examination","f-details",
      "f-academicType","f-academicTypeOther","f-consultantChoice","f-consultant-other",
      "f-age","f-sex","f-seminarType","f-seminarTypeOther","f-topic","f-venue"];
    var fieldFor = { "f-hospitalNumber":"hospitalNumber","f-date":"date","f-setting":"setting",
      "f-comments":"comments",
      "f-caseReport":"caseReport","f-otherSettingType":"otherSettingType","f-history":"history",
      "f-examination":"examination","f-details":"details","f-academicType":"academicType",
      "f-academicTypeOther":"academicTypeOther","f-consultantChoice":"consultantChoice",
      "f-consultant-other":"consultant", "f-age":"age","f-sex":"sex","f-seminarType":"seminarType",
      "f-seminarTypeOther":"seminarTypeOther","f-topic":"topic","f-venue":"venue" };
    ids.forEach(function(id){
      var node = el(id);
      if(node) f[fieldFor[id]] = node.value;
    });
  }
  // A multiPicker fieldKey is either a plain state.wiz.fields[key] array
  // (diagnoses, comorbidities, assistantsPicked) or, for a Surgical/Other
  // Procedure block's own procedures list, the path "pb:<index>:procedures"
  // -- these two getters/setters are the only place that distinction
  // matters, so mpToggle/mpAddExtra/mpRemoveExtra stay exactly as they were
  // for every existing caller.
  function mpFieldGet(key){
    if(key.indexOf("pb:")===0){
      var parts = key.split(":"); var block = (state.wiz.fields.procedureBlocks||[])[+parts[1]];
      return (block && block[parts[2]]) || [];
    }
    return state.wiz.fields[key]||[];
  }
  function mpFieldSet(key, arr){
    if(key.indexOf("pb:")===0){
      var parts = key.split(":"); var block = (state.wiz.fields.procedureBlocks||[])[+parts[1]];
      if(block) block[parts[2]] = arr;
      return;
    }
    state.wiz.fields[key] = arr;
  }
  function mpToggle(key, value, checked){
    syncWizFieldsFromDom();
    var arr = mpFieldGet(key).slice();
    var i = arr.indexOf(value);
    if(checked && i===-1) arr.push(value);
    if(!checked && i!==-1) arr.splice(i,1);
    mpFieldSet(key, arr);
    render();
  }
  function mpAddExtra(key, value){
    syncWizFieldsFromDom();
    value = (value||"").trim();
    if(!value) return;
    var arr = mpFieldGet(key).slice();
    if(arr.indexOf(value)===-1) arr.push(value);
    mpFieldSet(key, arr);
    render();
  }
  function mpRemoveExtra(key, value){
    syncWizFieldsFromDom();
    var arr = mpFieldGet(key).filter(function(v){ return v!==value; });
    mpFieldSet(key, arr);
    render();
  }
  function wizSetSite(site){ syncWizFieldsFromDom(); state.wiz.fields.site = site; state.wiz.fields.procedures = []; render(); }

  // ---- Surgical/Other Procedure: repeatable site/procedure blocks ----
  // Each block is { site, procedures, laterality, role }. "Other Procedure"
  // entries don't have a laterality field at all (renderOtherBlock omits
  // it), so that key just stays "" and is ignored on submit for that type.
  function newProcedureBlock(usedSites){
    var nextCat = state.config.categories.filter(function(c){ return usedSites.indexOf(c.key)===-1; })[0] || state.config.categories[0] || {};
    return { site: nextCat.key||"", procedures: [], laterality: state.config.laterality[0]||"", role: state.config.roleLevels[0]||"" };
  }
  function wizAddBlock(){
    syncWizFieldsFromDom();
    var f = state.wiz.fields;
    var usedSites = f.procedureBlocks.map(function(b){ return b.site; });
    f.procedureBlocks.push(newProcedureBlock(usedSites));
    render();
  }
  function wizRemoveBlock(idx){
    syncWizFieldsFromDom();
    var f = state.wiz.fields;
    if(f.procedureBlocks.length<=1) return; // at least one site/procedure block is required
    f.procedureBlocks.splice(idx,1);
    render();
  }
  function wizSetBlockSite(idx, site){
    syncWizFieldsFromDom();
    var block = state.wiz.fields.procedureBlocks[idx];
    if(!block) return;
    block.site = site;
    block.procedures = []; // changing site invalidates whatever was picked from the old one, same as the old single-site wizSetSite
    render();
  }
  window.__entlog_setBlockField = function(idx, field, value){
    syncWizFieldsFromDom();
    var block = state.wiz.fields.procedureBlocks[idx];
    if(block) block[field] = value;
    render();
  };

  function resolvedConsultant(){
    var f = state.wiz.fields;
    if(f.consultantChoice && f.consultantChoice!=="__other__"){
      var c = state.consultantsList.filter(function(x){ return x.username===f.consultantChoice; })[0];
      return { consultant: c ? c.displayName : f.consultantChoice, consultantUsername: f.consultantChoice };
    }
    return { consultant: (el("f-consultant-other")||{}).value || "", consultantUsername: null };
  }

  async function submitSurgical(){
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ toast("Hospital number is required."); return; }
    var blocks = f.procedureBlocks||[];
    if(!blocks.length || blocks.some(function(b){ return !b.procedures || !b.procedures.length; })){
      toast(blocks.length>1 ? "Pick at least one procedure for each site." : "Pick at least one procedure performed."); return;
    }
    if(!f.diagnoses.length){ toast("Pick at least one diagnosis."); return; }
    var cons = resolvedConsultant();
    if(!cons.consultant.trim()){ toast("Supervising consultant is required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var caseReport = (el("f-caseReport")||{}).value || "No";
    var flatProcedures = [];
    blocks.forEach(function(b){ (b.procedures||[]).forEach(function(p){ flatProcedures.push(p); }); });
    var data = {
      authorUsername: state.user.username, entryType:"surgical", unit: unitForDate(state.user.postings, entryDate),
      procedureBlocks: blocks.map(function(b){ return { site:b.site, procedures:b.procedures, laterality:b.laterality||"", role:b.role }; }),
      procedures: flatProcedures, setting: (el("f-setting")||{}).value, date: entryDate,
      hospitalNumber: hospitalNumber.trim(), age: (el("f-age")||{}).value || "", sex: (el("f-sex")||{}).value,
      diagnoses: f.diagnoses, diagnosesSecondary: f.diagnosesSecondary||[], comorbidities: f.comorbidities,
      consultant: cons.consultant.trim(), consultantUsername: cons.consultantUsername,
      assistants: (f.assistantsPicked||[]).join(", "), comments: (el("f-comments")||{}).value || "",
      caseReport: caseReport
    };
    var editingId = state.wiz.editingId;
    try{
      if(editingId){
        var linkedCaseId = state.wiz.linkedCaseId || null;
        var origSnapshot = state.wiz.origSnapshot || null;
        await dUpdateEntry(editingId, data);
        state.wiz = null; state.myEntriesLoaded = false;
        toast("Entry updated.");
        state.view = "resident-entries";
        render();
        await loadForView();
        if(caseReport==="Yes" && linkedCaseId){
          // Already chained to an Interesting Case -- only bother asking if
          // something the two entries actually share has changed.
          if(!origSnapshot || sharedCaseFieldsChanged(origSnapshot, data)){
            if(confirm("This surgical entry is linked to an Interesting Case report. Apply these changes (Hospital Number, age/sex, diagnoses, co-morbidities, procedures) to that case entry too?")){
              await applyCaseSync(linkedCaseId, data);
            }
          }
        } else if(caseReport==="Yes" && !linkedCaseId){
          // Not linked yet, but the PG has now opted into a case report --
          // same chain that happens when this option is picked at creation.
          // (Must switch back to the "resident-log" view before starting the
          // wizard -- that's the only view that ever renders it.)
          state.view = "resident-log";
          toast("Entry updated. Add the interesting-case details below to finish the case report.");
          startWizard("case", { hospitalNumber:data.hospitalNumber, age:data.age, sex:data.sex, diagnoses:data.diagnoses.slice(), diagnosesSecondary:(data.diagnosesSecondary||[]).slice(), comorbidities:data.comorbidities.slice(), procedures:data.procedures.slice(), linkedFromId:editingId });
        }
        return;
      }
      var newId = await dAddEntry(data);
      state.myEntriesLoaded = false;
      if(caseReport==="Yes"){
        toast("Surgical entry logged. Add the interesting-case details below to finish the case report.");
        startWizard("case", { hospitalNumber:data.hospitalNumber, age:data.age, sex:data.sex, diagnoses:data.diagnoses.slice(), diagnosesSecondary:data.diagnosesSecondary.slice(), comorbidities:data.comorbidities.slice(), procedures:data.procedures.slice(), linkedFromId:newId });
        return;
      }
      state.wiz = null;
      toast("Entry logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  async function submitOther(){
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ toast("Hospital number is required."); return; }
    var blocks = f.procedureBlocks||[];
    if(!blocks.length || blocks.some(function(b){ return !b.procedures || !b.procedures.length; })){
      toast(blocks.length>1 ? "Pick at least one procedure for each site." : "Pick at least one procedure performed."); return;
    }
    if(!f.diagnoses.length){ toast("Pick at least one diagnosis."); return; }
    var cons = resolvedConsultant();
    if(!cons.consultant.trim()){ toast("Supervising consultant is required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var flatProcedures = [];
    blocks.forEach(function(b){ (b.procedures||[]).forEach(function(p){ flatProcedures.push(p); }); });
    var data = {
      authorUsername: state.user.username, entryType:"other", unit: unitForDate(state.user.postings, entryDate),
      otherSettingType: (el("f-otherSettingType")||{}).value,
      procedureBlocks: blocks.map(function(b){ return { site:b.site, procedures:b.procedures, laterality:"", role:b.role }; }),
      procedures: flatProcedures,
      setting: (el("f-setting")||{}).value, date: entryDate, hospitalNumber: hospitalNumber.trim(),
      age: (el("f-age")||{}).value || "", sex: (el("f-sex")||{}).value,
      diagnoses: f.diagnoses, diagnosesSecondary: f.diagnosesSecondary||[], comorbidities: f.comorbidities,
      consultant: cons.consultant.trim(), consultantUsername: cons.consultantUsername,
      assistants: (f.assistantsPicked||[]).join(", "), comments: (el("f-comments")||{}).value || ""
    };
    var otherEditingId = state.wiz.editingId;
    try{
      if(otherEditingId){ await dUpdateEntry(otherEditingId, data); } else { await dAddEntry(data); }
      state.wiz = null; state.myEntriesLoaded = false;
      toast(otherEditingId ? "Entry updated." : "Entry logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  async function submitCase(){
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ toast("Hospital number is required."); return; }
    if(!f.diagnoses.length){ toast("Pick at least one diagnosis."); return; }
    var history = (el("f-history")||{}).value || "";
    if(!history.trim()){ toast("Brief history is required."); return; }
    var examination = (el("f-examination")||{}).value || "";
    if(!examination.trim()){ toast("Examination findings are required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var data = {
      authorUsername: state.user.username, entryType:"case", unit: unitForDate(state.user.postings, entryDate),
      date: entryDate, hospitalNumber: hospitalNumber.trim(), age: (el("f-age")||{}).value || "", sex: (el("f-sex")||{}).value,
      diagnoses: f.diagnoses, diagnosesSecondary: f.diagnosesSecondary||[], comorbidities: f.comorbidities,
      procedures: f.procedures, history: history.trim(), examination: examination.trim(),
      comments: (el("f-comments")||{}).value || "", linkedFromId: state.wiz.linkedFromId || null
    };
    var caseEditingId = state.wiz.editingId;
    try{
      if(caseEditingId){ await dUpdateEntry(caseEditingId, data); } else { await dAddEntry(data); }
      state.wiz = null; state.myEntriesLoaded = false;
      toast(caseEditingId ? "Case updated." : "Case logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this case. Please try again."); }
  }

  async function submitSeminar(){
    var typeVal = (el("f-seminarType")||{}).value;
    var typeOther = (el("f-seminarTypeOther")||{}).value || "";
    if(typeVal==="Other" && !typeOther.trim()){ toast("Describe the activity type."); return; }
    var topic = (el("f-topic")||{}).value || "";
    if(!topic.trim()){ toast("Give the seminar/presentation a topic or title."); return; }
    var details = (el("f-details")||{}).value || "";
    if(!details.trim()){ toast("Details are required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var data = {
      authorUsername: state.user.username, entryType:"seminar", unit: unitForDate(state.user.postings, entryDate),
      date: entryDate, seminarType: typeVal, seminarTypeOther: typeVal==="Other" ? typeOther.trim() : "",
      topic: topic.trim(), venue: (el("f-venue")||{}).value || "", details: details.trim()
    };
    var seminarEditingId = state.wiz.editingId;
    try{
      if(seminarEditingId){ await dUpdateEntry(seminarEditingId, data); } else { await dAddEntry(data); }
      state.wiz = null; state.myEntriesLoaded = false;
      toast(seminarEditingId ? "Entry updated." : "Seminar/presentation logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  async function submitAcademic(){
    var f = state.wiz.fields;
    var typeVal = (el("f-academicType")||{}).value;
    var typeOther = (el("f-academicTypeOther")||{}).value || "";
    if(typeVal==="Other" && !typeOther.trim()){ toast("Describe the activity type."); return; }
    var details = (el("f-details")||{}).value || "";
    if(!details.trim()){ toast("Details are required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var data = {
      authorUsername: state.user.username, entryType:"academic", unit: unitForDate(state.user.postings, entryDate),
      date: entryDate, academicType: typeVal, academicTypeOther: typeVal==="Other" ? typeOther.trim() : "",
      details: details.trim()
    };
    var academicEditingId = state.wiz.editingId;
    try{
      if(academicEditingId){ await dUpdateEntry(academicEditingId, data); } else { await dAddEntry(data); }
      state.wiz = null; state.myEntriesLoaded = false;
      toast(academicEditingId ? "Entry updated." : "Academic activity logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this activity. Please try again."); }
  }

  async function removeEntry(id){
    if(!confirm("Delete this entry? This cannot be undone.")) return;
    try{
      await dDeleteEntry(id);
      state.myEntries = state.myEntries.filter(function(e){ return e.id!=id; });
      render();
      toast("Entry deleted.");
    }catch(e){ toast("Could not delete this entry."); }
  }

  /* ============================================================
     DEVELOPER ACTIONS
  ============================================================ */
  async function setUserRole(username, newRole){
    try{
      await dUpdateUser(username, {role:newRole});
      state.devUsers = state.devUsers.map(function(u){ if(u.username===username) u.role=newRole; return u; });
      render();
      toast("Role updated for "+username+".");
    }catch(e){ toast("Could not update role."); }
  }
  async function setUserActive(username, active){
    try{
      await dUpdateUser(username, {active:active});
      function applyActive(list){ return list.map(function(u){ if(u.username===username) u.active=active; return u; }); }
      state.devUsers = applyActive(state.devUsers);
      state.manageUsers = applyActive(state.manageUsers);
      render();
      toast(active ? "Account reactivated." : "Account deactivated.");
    }catch(e){ toast("Could not update account status."); }
  }
  async function updateUserProfile(username, patch){
    try{
      await dUpdateUser(username, patch);
      function applyProfile(list){ return list.map(function(u){ return u.username===username ? Object.assign({}, u, patch) : u; }); }
      state.devUsers = applyProfile(state.devUsers);
      state.manageUsers = applyProfile(state.manageUsers);
      render();
      toast("Profile updated for "+username+".");
    }catch(e){ toast(e.message || "Could not update this profile."); }
  }
  async function deleteUserAccount(username){
    if(!confirm("Delete "+username+"’s account? This cannot be undone. Accounts with logged entries can't be deleted this way — deactivate them instead.")) return;
    try{
      await dDeleteUser(username);
      state.devUsers = state.devUsers.filter(function(u){ return u.username!==username; });
      state.manageUsers = state.manageUsers.filter(function(u){ return u.username!==username; });
      render();
      toast("Account deleted.");
    }catch(e){ toast(e.message || "Could not delete this account."); }
  }
  async function approveSignupRequest(username){
    try{
      await dApproveSignup(username);
      state.signupRequests = state.signupRequests.filter(function(u){ return u.username!==username; });
      render();
      toast("Approved "+username+" — they can now sign in.");
    }catch(e){ toast(e.message || "Could not approve this account."); }
  }
  async function rejectSignupRequest(username){
    if(!confirm("Reject and delete this sign-up request? The person will need to sign up again.")) return;
    try{
      await dRejectSignup(username);
      state.signupRequests = state.signupRequests.filter(function(u){ return u.username!==username; });
      render();
      toast("Sign-up request rejected.");
    }catch(e){ toast(e.message || "Could not reject this request."); }
  }
  async function adminCreateUser(fields){
    try{
      var username = cleanUsername(fields.username);
      if(username.length < 3){ toast("Username must be at least 3 characters."); return; }
      if((fields.password||"").length < 8){ toast("Password must be at least 8 characters."); return; }
      await dCreateUser(username, {
        password: fields.password, role: fields.role, displayName: fields.displayName || username,
        pgYear: fields.pgYear, designation: fields.designation, unit: fields.unit
      });
      state.devUsersLoaded = false;
      state.showCreateUserForm = false;
      toast("Account created for "+username+".");
      render();
      loadDevUsers();
    }catch(e){ toast(e.message || "Could not create this account."); }
  }
  async function adminResetPassword(requestId, username, newPassword){
    if(!newPassword || newPassword.length < 8){ toast("New password must be at least 8 characters."); return; }
    try{
      await dUpdateUser(username, {password: newPassword});
      if(requestId){
        await dResolvePasswordRequest(requestId);
        state.passwordResets = state.passwordResets.map(function(r){ if(r.id==requestId){ r.status="resolved"; r.resolvedBy=state.user.username; } return r; });
      }
      toast("Password reset for "+username+".");
      render();
    }catch(e){ toast(e.message || "Could not reset this password."); }
  }

  async function addRoleAssignment(consultantUsername, role, unit, startAt, endAt){
    if(!consultantUsername){ toast("Pick a consultant."); return; }
    if(!startAt || !endAt){ toast("Set both a start and an end date/time."); return; }
    if(new Date(endAt).getTime() <= new Date(startAt).getTime()){ toast("End must be after start."); return; }
    if(role==="head_of_unit" && !unit){ toast("Head of Unit needs a unit."); return; }
    var consultant = state.devUsers.filter(function(u){ return u.username===consultantUsername; })[0];
    var data = {
      consultantUsername: consultantUsername,
      consultantDisplayName: consultant ? consultant.displayName : consultantUsername,
      role: role, unit: role==="head_of_unit" ? unit : "",
      startAt: startAt, endAt: endAt, assignedBy: state.user.username, assignedAt: new Date().toISOString()
    };
    try{
      var id = await dAddRoleAssignment(data);
      state.roleAssignments = state.roleAssignments.concat([Object.assign({id:id}, data)]);
      toast("Appointment added.");
      render();
    }catch(e){ toast("Could not add this appointment."); }
  }
  async function removeRoleAssignment(id){
    if(!confirm("End this appointment now?")) return;
    try{
      await dRemoveRoleAssignment(id);
      state.roleAssignments = state.roleAssignments.filter(function(a){ return a.id!=id; });
      render();
      toast("Appointment ended.");
    }catch(e){ toast("Could not remove this appointment."); }
  }

  // Whether a role assignment (HOD / Course Coordinator / Head of Unit) is
  // currently in force, given its start/end datetime-local strings. No end
  // means open-ended; no start means already started.
  function isAssignmentActive(a){
    var now = Date.now();
    var start = a.startAt ? new Date(a.startAt).getTime() : null;
    var end = a.endAt ? new Date(a.endAt).getTime() : null;
    return (start===null || start<=now) && (end===null || now<=end);
  }

  async function addUnit(fullName, shortForm, group){
    fullName=(fullName||"").trim(); shortForm=(shortForm||"").trim();
    if(!fullName || !shortForm){ toast("Enter both a full name and a short form."); return; }
    var key = uniqueUnitKey(slugify(shortForm));
    group = group||"Peripheral Postings";
    // Insert alphabetically by full name within its own group, rather than
    // appending -- so a newly added unit lands where a resident scanning
    // the (now alphabetized) list would expect to find it, without
    // disturbing the other group.
    var list = (state.config.units||[]).slice();
    var groupIndices = [];
    list.forEach(function(u,i){ if(u.group===group) groupIndices.push(i); });
    var insertAt = list.length; // default: new group, or sorts after every existing member -> end of its block
    if(groupIndices.length){
      insertAt = groupIndices[groupIndices.length-1]+1;
      for(var k=0;k<groupIndices.length;k++){
        if(String(list[groupIndices[k]].fullName).localeCompare(fullName, undefined, {sensitivity:"base"})>=0){
          insertAt = groupIndices[k];
          break;
        }
      }
    }
    list.splice(insertAt, 0, {key:key, fullName:fullName, shortForm:shortForm, group:group});
    try{
      await dUpdateConfig({units:list});
      state.config.units = list;
      toast("Unit added.");
      render();
    }catch(e){ toast("Could not add unit."); }
  }
  async function removeUnit(key){
    if(!confirm("Remove this unit? Residents' historical postings keep the old unit name as plain text.")) return;
    var list = (state.config.units||[]).filter(function(u){ return u.key!==key; });
    try{
      await dUpdateConfig({units:list});
      state.config.units = list;
      render();
    }catch(e){ toast("Could not remove unit."); }
  }

  /* ---------- Manage Lists ---------- */
  function uniqueCatKey(base){
    var existing = state.config.categories.map(function(c){ return c.key; });
    var key = base, n = 2;
    while(existing.indexOf(key) !== -1){ key = base + "-" + n; n++; }
    return key;
  }
  async function addCategory(name, color){
    name = (name||"").trim();
    if(!name){ toast("Give the new site a name."); return; }
    var key = uniqueCatKey(slugify(name));
    var newCategories = state.config.categories.concat([{key:key, name:name, color: color || "var(--teal)"}]);
    var patch = { categories: newCategories, procedures: {} };
    patch.procedures[key] = [];
    try{
      await dUpdateConfig(patch);
      state.config.categories = newCategories;
      state.config.procedures[key] = [];
      state.devListDraft.selectedCat = key;
      toast("Site added.");
      render();
    }catch(e){ toast("Could not add site."); }
  }
  async function removeCategory(key){
    if(!confirm("Remove this site? Its procedure list goes with it. Already-logged entries keep the old site name as plain text.")) return;
    var newCategories = state.config.categories.filter(function(c){ return c.key!==key; });
    try{
      await dUpdateConfig({ categories: newCategories });
      state.config.categories = newCategories;
      if(state.devListDraft.selectedCat===key){ state.devListDraft.selectedCat = newCategories.length ? newCategories[0].key : null; }
      toast("Site removed.");
      render();
    }catch(e){ toast("Could not remove site."); }
  }
  async function editCategory(key, name, color){
    var newCategories = state.config.categories.map(function(c){
      if(c.key!==key) return c;
      return { key:c.key, name: (name||"").trim() || c.name, color: color || c.color };
    });
    try{
      await dUpdateConfig({ categories: newCategories });
      state.config.categories = newCategories;
      toast("Site updated.");
      render();
    }catch(e){ toast("Could not update site."); }
  }
  async function addProcedure(catKey, text){
    text = (text||"").trim();
    if(!text){ return; }
    var list = (state.config.procedures[catKey] || []).slice();
    list.splice(sortedInsertIndex(list, text), 0, text);
    var patch = { procedures: {} }; patch.procedures[catKey] = list;
    try{
      await dUpdateConfig(patch);
      state.config.procedures[catKey] = list;
      toast("Procedure added.");
      render();
    }catch(e){ toast("Could not add procedure."); }
  }
  // Removes by value rather than array index -- the admin screen renders
  // this list alphabetized (see renderDeveloperLists), so a "Remove" button
  // built from the sorted render's position would delete the wrong item the
  // moment display order and storage order diverge (exactly the class of
  // stale-index bug fixed elsewhere in this app's PATCH handling).
  async function removeProcedure(catKey, value){
    var list = (state.config.procedures[catKey] || []).filter(function(p){ return p!==value; });
    var patch = { procedures: {} }; patch.procedures[catKey] = list;
    try{
      await dUpdateConfig(patch);
      state.config.procedures[catKey] = list;
      render();
    }catch(e){ toast("Could not remove procedure."); }
  }

  // `sortable:true` marks a list as an unordered pool of choices, shown and
  // added-to alphabetically. Left off (roleLevels, pgYears) for the two
  // lists whose existing order IS the information -- an escalating
  // entrustment scale and JR-1/2/3 -- where alphabetizing would scramble
  // exactly the ordering the list exists to preserve. The remaining short
  // lists (settings, laterality, academicTypes, otherProcedureSettings,
  // sexOptions, seminarTypes) are left in admin-defined order too: at 2-4
  // items each, alphabetizing buys nothing and isn't part of what the
  // resident is actually trying to find faster.
  var SIMPLE_LISTS = [
    { key:"roleLevels", title:"Entrustment / role levels", hint:"Shown on every procedure entry, in this order." },
    { key:"pgYears", title:"PG year options", hint:"Shown at resident sign-up." },
    { key:"settings", title:"Emergency / Elective options", hint:"Shown on Surgical and Other procedure entries." },
    { key:"laterality", title:"Side of procedure options", hint:"Shown on Surgical procedure entries." },
    { key:"diagnoses", title:"Diagnosis options", hint:"Multi-select on every entry type; residents can also add one not on the list.", sortable:true },
    { key:"comorbidities", title:"Comorbidity options", hint:"Multi-select on every entry type; residents can also add one not on the list.", sortable:true },
    { key:"academicTypes", title:"Academic activity types", hint:"Shown on Academic Participation entries (plus a free-text “Other”)." },
    { key:"otherProcedureSettings", title:"“Other procedure” setting types", hint:"OPD / bedside / emergency department / treatment room, or your own equivalents." },
    { key:"sexOptions", title:"Sex options", hint:"Shown on Surgical, Other procedure and Interesting Case entries." },
    { key:"seminarTypes", title:"Seminar / presentation types", hint:"Shown on Seminar / Presentation entries (plus a free-text “Other”)." }
  ];
  function simpleListSpec(listKey){ return SIMPLE_LISTS.filter(function(s){ return s.key===listKey; })[0]; }
  async function addListItem(listKey, text){
    text = (text||"").trim();
    if(!text) return;
    var sortable = !!(simpleListSpec(listKey)||{}).sortable;
    var list = (state.config[listKey] || []).slice();
    if(sortable) list.splice(sortedInsertIndex(list, text), 0, text);
    else list.push(text);
    var patch = {}; patch[listKey] = list;
    try{
      await dUpdateConfig(patch);
      state.config[listKey] = list;
      render();
    }catch(e){ toast("Could not add option."); }
  }
  // Value-based removal for a sortable (alphabetized-on-render) list, same
  // reasoning as removeProcedure; index-based removal is still correct and
  // unchanged for the non-sortable lists, whose render order always matches
  // storage order.
  async function removeListItem(listKey, idxOrValue){
    var sortable = !!(simpleListSpec(listKey)||{}).sortable;
    var list = (state.config[listKey] || []).slice();
    if(sortable) list = list.filter(function(v){ return v!==idxOrValue; });
    else list.splice(idxOrValue,1);
    var patch = {}; patch[listKey] = list;
    try{
      await dUpdateConfig(patch);
      state.config[listKey] = list;
      render();
    }catch(e){ toast("Could not remove option."); }
  }

  function toCSV(rows, columns){
    var lines = [columns.map(function(c){ return c.label; }).join(",")];
    rows.forEach(function(r){
      lines.push(columns.map(function(c){
        var v = typeof c.get === "function" ? c.get(r) : r[c.key];
        if(Array.isArray(v)) v = v.join("; ");
        v = (v==null) ? "" : String(v);
        v = v.replace(/"/g,'""');
        if(/[",\n]/.test(v)) v = '"'+v+'"';
        return v;
      }).join(","));
    });
    return lines.join("\n");
  }
  function exportEntriesCSV(){
    // A real file download via the server's Content-Disposition header --
    // no special capability needed, works in any browser.
    window.location.href = "/api/entries/export.csv";
  }
  function exportUsersCSV(){
    window.location.href = "/api/users/export.csv";
  }
  // Self-service export for every role -- scoped server-side to whatever the
  // caller can already see (their own entries for a trainee; scope-filtered
  // entries for a consultant; everything for Developer, who also has the
  // separate all-accounts export above).
  function exportMyEntriesCSV(){
    window.location.href = "/api/entries/export/mine.csv";
  }

  /* ============================================================
     RENDER: AUTH SCREENS
  ============================================================ */
  function renderLogin(){
    return ''+
    '<div class="center-shell"><div class="auth-card">'+
      '<div class="auth-eyebrow">ENT Postgraduate Programme</div>'+
      '<h1>ENT Surgical Logbook</h1>'+
      '<div class="auth-sub">Sign in to log de-identified cases and track competency progress.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label for="login-username">Username</label><input id="login-username" type="text" autocomplete="username" placeholder="e.g. devashish.pg"></div>'+
      '<div class="field"><label for="login-password">Password</label><input id="login-password" type="password" autocomplete="current-password" placeholder="••••••"></div>'+
      '<button class="btn btn-primary" style="width:100%" id="btn-login" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Signing in…":"Sign in")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">No account yet? <button class="link-btn" id="go-signup">Create one</button></div>'+
      '<div style="text-align:center; margin-top:8px; font-size:12.5px;" class="muted">Forgot your password? <button class="link-btn" id="go-forgot">Request a reset</button></div>'+
      // Deliberately the least prominent thing on this screen: this is a
      // developer/maintainer path, not a third self-service option for a
      // trainee or consultant, so it doesn't get the same visual weight as
      // "Create one" / "Request a reset" above -- separated by its own
      // divider, smaller, and low-contrast rather than a third equal link.
      '<div style="text-align:center; margin-top:18px; padding-top:12px; border-top:1px solid var(--line); font-size:11px;" class="muted"><button class="link-btn" id="go-devlogin" style="font-size:11px; color:var(--ink-soft);">Developer sign-in</button></div>'+
    '</div></div>';
  }

  function renderForgot(){
    return ''+
    '<div class="center-shell"><div class="auth-card">'+
      '<div class="auth-eyebrow">Password reset</div>'+
      '<h1>Request a new password</h1>'+
      '<div class="auth-sub">Your Developer admin sets the new password by hand — this just puts your request in their queue.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label for="forgot-username">Username</label><input id="forgot-username" type="text" autocomplete="username"></div>'+
      '<div class="field"><label for="forgot-note">Note for your admin (optional)</label><textarea id="forgot-note" placeholder="Anything that helps them confirm it&#39;s you"></textarea></div>'+
      '<button class="btn btn-primary" style="width:100%" id="btn-forgot" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Sending…":"Send request")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Remembered it? <button class="link-btn" id="go-login-from-forgot">Back to sign in</button></div>'+
    '</div></div>';
  }

  function renderDevLogin(){
    return ''+
    '<div class="center-shell"><div class="auth-card">'+
      '<div class="auth-eyebrow">Developer sign-in</div>'+
      '<h1>Manage the logbook</h1>'+
      '<div class="auth-sub">Separate from resident/consultant sign-in. Only accounts already granted the Developer role can enter here.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label for="dev-username">Developer username</label><input id="dev-username" type="text" autocomplete="username"></div>'+
      '<div class="field"><label for="dev-password">Password</label><input id="dev-password" type="password" autocomplete="current-password"></div>'+
      '<button class="btn btn-primary" style="width:100%" id="btn-devlogin" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Signing in…":"Sign in as Developer")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Not a developer? <button class="link-btn" id="go-login-from-dev">Back to regular sign-in</button></div>'+
    '</div></div>';
  }

  function renderSignup(){
    var role = state.signupRole;
    var isTrainee = isTraineeRole(role);
    return ''+
    '<div class="center-shell"><div class="auth-card" style="max-width:460px;">'+
      '<div class="auth-eyebrow">ENT Postgraduate Programme</div>'+
      '<h1>Create your account</h1>'+
      '<div class="auth-sub">De-identified logging only — log by Hospital Number, never a patient’s name.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label>I am a</label><div class="radio-group">'+
        radioCard("signup-role","resident",role==="resident","PG Resident","Log your own surgeries, procedures and interesting cases.")+
        radioCard("signup-role","senior_resident",role==="senior_resident","Senior Resident","Same logbook and dashboard as a PG Resident.")+
        radioCard("signup-role","fellow",role==="fellow","Fellow","Same logbook and dashboard as a PG Resident.")+
        radioCard("signup-role","consultant",role==="consultant","Consultant / Faculty","View trainee progress in your unit.")+
      '</div></div>'+
      '<div class="field"><label for="su-username">Username</label><input id="su-username" type="text" placeholder="e.g. devashish.pg"></div>'+
      '<div class="row2">'+
        '<div class="field"><label for="su-password">Password</label><input id="su-password" type="password"></div>'+
        '<div class="field"><label for="su-confirm">Confirm password</label><input id="su-confirm" type="password"></div>'+
      '</div>'+
      '<div class="field"><label for="su-displayName">Display name</label><input id="su-displayName" type="text" placeholder="e.g. Dr. Devashish Chaudhary"></div>'+
      (isTrainee ?
        '<div class="field"><label for="su-pgYear">Batch / Year</label><select id="su-pgYear">'+state.config.pgYears.map(function(o){return '<option>'+o+'</option>';}).join("")+'</select></div>'+
        (role==="fellow" ?
          '<div class="field"><label for="su-unit-search">Parent / home unit</label>'+searchSingleField("su-unit", unitSearchOptions(), null, "Search units…")+'</div>'+
          '<p class="hint">This is your home unit for the fellowship — you can still log peripheral postings in other units under My Postings after signing in.</p>'
          :
          '<p class="hint">You’ll add your unit posting (with dates) after signing in, under My Postings.</p>'
        )
        :
        '<div class="row2">'+
          '<div class="field"><label for="su-designation">Designation</label><select id="su-designation">'+opts_(state.config.consultantDesignations, state.config.consultantDesignations[0])+'</select></div>'+
          '<div class="field"><label for="su-unit-search">Department / unit</label>'+searchSingleField("su-unit", unitSearchOptions(), null, "Search units…")+'</div>'+
        '</div>'
      )+
      '<p class="hint">Your account needs approval before you can sign in — a Head of Department, Course Coordinator'+(role==="fellow"?", Head of Unit,":"")+' or Developer will review it.</p>'+
      '<button class="btn btn-primary" style="width:100%; margin-top:6px;" id="btn-signup" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Creating account…":"Create account")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Already have an account? <button class="link-btn" id="go-login">Sign in</button></div>'+
    '</div></div>';
  }

  function renderSignupPending(){
    return ''+
    '<div class="center-shell"><div class="auth-card" style="text-align:center;">'+
      '<div class="auth-eyebrow">Account created</div>'+
      '<h1>Awaiting approval</h1>'+
      '<div class="auth-sub">'+esc(state.signupPendingMessage)+'</div>'+
      '<button class="btn btn-primary" style="width:100%; margin-top:16px;" id="go-login-from-pending">Back to sign in</button>'+
    '</div></div>';
  }

  function radioCard(name, value, checked, title, desc){
    return '<label class="radio-card"><input type="radio" name="'+name+'" value="'+value+'" '+(checked?"checked":"")+'><span><span class="t">'+esc(title)+'</span><br><span class="d">'+esc(desc)+'</span></span></label>';
  }
  function opts_(list, selected){
    return list.map(function(o){ return '<option '+(o===selected?"selected":"")+'>'+esc(o)+'</option>'; }).join("");
  }
  function statTile(num, label, iconKey){
    return '<div class="stat-tile">'+(iconKey?icon(iconKey):'')+'<div><div class="num">'+num+'</div><div class="lbl">'+esc(label)+'</div></div></div>';
  }
  function barRow(label, count, max, color, iconKey){
    var pct = max>0 ? Math.round((count/max)*100) : 0;
    return '<div class="bar-row"><div class="bar-label">'+(iconKey?icon(iconKey):'')+'<span>'+esc(label)+'</span></div><div class="bar-track"><span class="bar-fill" style="width:'+pct+'%; background:'+(color||"var(--teal)")+';"></span></div><div class="bar-count">'+count+'</div></div>';
  }

  /* ============================================================
     RENDER: SHELL
  ============================================================ */
  function pendingPasswordRequestCount(){
    return state.passwordResets.filter(function(r){ return r.status==="pending"; }).length;
  }
  function navItems(){
    var caps = state.capabilities || {};
    if(isTraineeRole(state.user.role)) return [["dashboard","Dashboard"],["resident-log","Log Entry"],["resident-entries","My Entries"],["resident-progress","My Progress"],["resident-postings","My Postings"],["account","My Account"],["about","About / Roadmap"]];
    if(state.user.role==="consultant"){
      var items = [["dashboard","Dashboard"],["consultant-roster","Roster"]];
      if(caps.canApprove) items.push(["signup-approvals","Approvals"]);
      if(caps.canManageProfiles) items.push(["manage-users","Manage Users"]);
      items.push(["account","My Account"],["about","About / Roadmap"]);
      return items;
    }
    return [["dashboard","Dashboard"],["developer-users","Users"],["signup-approvals","Approvals"],["developer-password-requests","Password Requests"],["developer-lists","Manage Lists"],["developer-roles","Units & Roles"],["developer-data","Data & Export"],["account","My Account"],["about","About / Roadmap"]];
  }
  function renderShell(inner){
    var role = state.user.role;
    var roleLabelText = roleLabel(role);
    var pendingCount = role==="developer" ? pendingPasswordRequestCount() : 0;
    return ''+
    '<div class="topbar">'+
      '<div class="brand">'+
        '<button type="button" class="nav-toggle" id="btn-nav-toggle" aria-label="'+(state.mobileNavOpen?"Close menu":"Open menu")+'">'+icon(state.mobileNavOpen?"close":"menu")+'</button>'+
        '<div class="brand-mark">EL</div><div class="brand-text"><h1>ENT Surgical Logbook</h1><div class="sub">'+"De-identified logbook"+'</div></div>'+
      '</div>'+
      '<div class="user-chip"><span class="role-badge">'+esc(roleLabelText)+'</span><span>'+esc(state.user.displayName)+'</span><button class="btn btn-ghost btn-sm" id="btn-logout">Log out</button></div>'+
    '</div>'+
    '<div class="shell-body">'+
      '<nav class="sidenav'+(state.mobileNavOpen?" open":"")+'">'+navItems().map(function(item){
        var badge = "";
        if(item[0]==="developer-password-requests" && pendingCount>0) badge = '<span class="alert-count">'+pendingCount+'</span>';
        if(item[0]==="signup-approvals" && state.signupRequests.length>0) badge = '<span class="alert-count">'+state.signupRequests.length+'</span>';
        return '<button data-nav="'+item[0]+'" class="'+(state.view===item[0]?"active":"")+'">'+esc(item[1])+badge+'</button>';
      }).join("")+'</nav>'+
      '<main'+((state.view==="resident-entries"||state.view==="consultant-detail")?' class="wide"':'')+'>'+
        (state.toast ? '<div class="success-banner">'+esc(state.toast)+'</div>' : '')+
        inner+
      '</main>'+
    '</div>'+
    '<div class="footer-note">De-identified data only</div>';
  }

  function dashCard(navTo, title, desc, badge, iconKey, iconColor){
    return '<button class="dash-card" data-nav="'+navTo+'"><div class="icn" style="'+(iconColor?"color:"+iconColor+";":"")+'">'+(iconKey?icon(iconKey):esc(title.slice(0,1)))+'</div><div class="t">'+esc(title)+(badge?badge:"")+'</div><div class="d">'+esc(desc)+'</div></button>';
  }

  // Backend sends structured facts, not copy -- composing the sentence here
  // (using our own unit-label helpers) keeps unit-name formatting consistent
  // with the rest of the app, and lets us show only the single
  // highest-priority reminder (reminders[0], already sorted server-side) so
  // the dashboard never stacks more than one nudge at a time.
  function composeReminderText(r){
    if(r.type==="end_of_posting"){
      var unitLabel = unitShortHtml(r.unit) + ' <span class="muted">('+esc(unitFull(r.unit))+')</span>';
      var when = r.daysLeft===0 ? "ends today" : "ends in "+r.daysLeft+" day"+(r.daysLeft===1?"":"s");
      var msg = "Your posting in "+unitLabel+" "+when+".";
      if(!r.hasNextPosting) msg += " No new posting is on file yet — add one under My Postings when you know it.";
      return msg;
    }
    if(r.type==="weekly"){
      var msg = r.weekCount>0
        ? ("You've logged "+r.weekCount+" entr"+(r.weekCount===1?"y":"ies")+" in the last 7 days.")
        : "You haven't logged any entries in the last 7 days.";
      if(r.pendingPapers!=null && r.pendingPapers>0){
        msg += " "+r.pendingPapers+" case write-up"+(r.pendingPapers===1?"":"s")+" still pending — see the Write-up column in My Entries.";
      }
      return msg;
    }
    if(r.type==="daily"){
      if(!r.lastEntryDate) return "You haven't logged your first entry yet — whenever you're ready.";
      var days = Math.round((new Date(todayISO()+"T00:00:00") - new Date(r.lastEntryDate+"T00:00:00")) / 86400000);
      return "You haven't logged an entry in "+days+" day"+(days===1?"":"s")+".";
    }
    return "";
  }
  function reminderBanner(){
    if(!state.reminders || state.reminders.length===0) return "";
    var r = state.reminders[0];
    if(state.dismissedReminderKey===r.type) return "";
    return '<div class="reminder-banner"><span>'+composeReminderText(r)+'</span>'+
      '<button type="button" class="reminder-dismiss" data-dismiss-reminder="'+esc(r.type)+'" aria-label="Dismiss reminder">×</button></div>';
  }

  function renderDashboardResident(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var s = computeStats(state.myEntries);
    var todayUnit = unitForDate(state.user.postings, todayISO());
    var recent = state.myEntries.slice().sort(function(a,b){ return (b.date||"").localeCompare(a.date||""); }).slice(0,5);
    return ''+
    reminderBanner()+
    (todayUnit ? '<div class="notice-banner" style="background:var(--teal-bg); color:var(--teal-ink); border-color:var(--teal);">Current posting: '+unitShortHtml(todayUnit)+' — '+esc(unitFull(todayUnit))+'</div>'
      : '<div class="notice-banner">You don’t have a current posting on file — add one under My Postings so your entries can be tagged with a unit.</div>')+
    '<div class="stat-grid">'+
      statTile(s.total,"Total entries")+statTile(s.surgical,"Surgical","surgical")+statTile(s.other,"Other procedures","other")+statTile(s["case"],"Interesting cases","case")+statTile(s.academic,"Academic","academic")+statTile(s.seminar,"Seminars given","seminar")+
    '</div>'+
    '<div class="card"><span class="eyebrow">New entry</span><h2>Log a new entry</h2><div class="dash-grid" style="margin-top:14px;">'+
      dashCard("__new-surgical","Surgical Procedure","Any operative case, OT-booked.",null,"surgical","var(--teal)")+
      dashCard("__new-other","Other Procedure","OPD, bedside, ED or treatment-room procedures.",null,"other","var(--amber)")+
      dashCard("__new-case","Interesting Case","Rare presentations, diagnostic dilemmas.",null,"case","var(--ink-soft)")+
      dashCard("__new-academic","Academic Participation","CME, journal club, papers, university activity.",null,"academic","var(--green)")+
      dashCard("__new-seminar","Seminar / Presentation","Seminars, lectures or case presentations you conducted.",null,"seminar","var(--violet)")+
    '</div></div>'+
    '<div class="card"><div class="section-head"><h2>Recent entries</h2></div>'+
      (recent.length===0 ? '<div class="empty-state">Nothing logged yet.</div>' :
      '<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Summary</th><th>Unit</th></tr></thead><tbody>'+
        recent.map(function(e){ return '<tr><td class="tabular">'+fmtDate(e.date)+'</td><td>'+entryTypeChip(e)+'</td><td>'+esc(summarizeEntry(e))+'</td><td>'+unitShortHtml(e.unit)+'</td></tr>'; }).join("")+
      '</tbody></table></div>')+
    '</div>';
  }

  function renderDashboardConsultant(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var caps = state.capabilities || {};
    var allEntries = [];
    state.roster.forEach(function(r){ allEntries = allEntries.concat(r.entries); });
    var s = computeStats(allEntries);
    return ''+
    renderScopeBanner()+
    '<div class="stat-grid">'+
      statTile(state.roster.length,"Trainees visible")+statTile(s.total,"Total entries")+statTile(s.surgical,"Surgical","surgical")+statTile(s.other,"Other","other")+statTile(s["case"],"Cases","case")+statTile(s.academic,"Academic","academic")+statTile(s.seminar,"Seminars","seminar")+
    '</div>'+
    '<div class="card"><h2>Roster</h2><div class="dash-grid">'+dashCard("consultant-roster","Open Roster","See every trainee’s progress within your scope.",null,"users","var(--teal)")+'</div></div>'+
    ((caps.canApprove || caps.canManageProfiles) ? '<div class="card"><h2>Accounts</h2><div class="dash-grid">'+
      (caps.canApprove ? dashCard("signup-approvals","Approvals","Review pending sign-ups.", state.signupRequests.length>0?'<span class="alert-count">'+state.signupRequests.length+'</span>':"","approvals","var(--green)") : "")+
      (caps.canManageProfiles ? dashCard("manage-users","Manage Users","Update batches/designations, deactivate or delete accounts.",null,"users","var(--violet)") : "")+
    '</div></div>' : '');
  }

  function renderDashboardDeveloper(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var traineeCount = state.devUsers.filter(function(u){return isTraineeRole(u.role);}).length;
    var consultantCount = state.devUsers.filter(function(u){return u.role==="consultant";}).length;
    var pending = pendingPasswordRequestCount();
    return ''+
    (pending>0 ? '<div class="notice-banner">'+pending+' password reset request'+(pending>1?"s":"")+' waiting on you.</div>' : '')+
    '<div class="stat-grid">'+
      statTile(traineeCount,"Trainees")+statTile(consultantCount,"Consultants")+statTile(state.devAllEntries.length,"Total entries")+statTile((state.config.units||[]).length,"Units")+
    '</div>'+
    '<div class="card"><h2>Quick links</h2><div class="dash-grid">'+
      dashCard("developer-users","Users","Create, promote or deactivate accounts.",null,"users","var(--teal)")+
      dashCard("signup-approvals","Approvals","Review pending sign-ups.", state.signupRequests.length>0?'<span class="alert-count">'+state.signupRequests.length+'</span>':"","approvals","var(--green)")+
      dashCard("developer-password-requests","Password Requests","Set a new password for someone locked out.", pending>0?'<span class="alert-count">'+pending+'</span>':"","password","var(--amber)")+
      dashCard("developer-roles","Units & Roles","Manage the units list and Head of Unit / Coordinator / HOD appointments.",null,"units","var(--violet)")+
      dashCard("developer-lists","Manage Lists","Edit every dropdown trainees and consultants see.",null,"lists","var(--ink-soft)")+
      dashCard("developer-data","Data & Export","CSV export and storage status.",null,"export","var(--teal)")+
    '</div></div>';
  }

  function computeStats(entries){
    var counts = { total: entries.length, surgical:0, other:0, "case":0, academic:0, seminar:0 };
    var procCounts = {}, siteCounts = {}, unitCounts = {};
    entries.forEach(function(e){
      var t = normType(e);
      if(counts.hasOwnProperty(t)) counts[t]++;
      entryProcedures(e).forEach(function(p){ procCounts[p] = (procCounts[p]||0)+1; });
      if(t==="surgical" || t==="other"){
        // A combined multi-site case (e.g. Ear+Nose in one sitting) counts
        // toward EVERY site it actually touched, not just the first --
        // entrySite() alone would silently drop every site but the first
        // from this breakdown.
        var seenSites = {};
        entryProcedureBlocks(e).forEach(function(b){
          if(b.site && !seenSites[b.site]){ seenSites[b.site]=1; siteCounts[b.site] = (siteCounts[b.site]||0)+1; }
        });
      }
      if(e.unit) unitCounts[e.unit] = (unitCounts[e.unit]||0)+1;
    });
    var procRows = Object.keys(procCounts).map(function(p){ return {name:p, count:procCounts[p]}; }).sort(function(a,b){ return b.count-a.count; });
    var siteRows = Object.keys(siteCounts).map(function(k){ return {key:k, count:siteCounts[k]}; }).sort(function(a,b){ return b.count-a.count; });
    var unitRows = Object.keys(unitCounts).map(function(k){ return {key:k, count:unitCounts[k]}; }).sort(function(a,b){ return b.count-a.count; });
    return { total:counts.total, surgical:counts.surgical, other:counts.other, "case":counts["case"], academic:counts.academic, seminar:counts.seminar, procRows:procRows, siteRows:siteRows, unitRows:unitRows };
  }

  // Reverse lookup: which site category a procedure name belongs to, so the
  // "surgery-wise" breakdown can carry the same icon as its site. Falls back
  // to no icon for a free-text procedure that isn't in any default/custom list.
  function procedureCategoryKey(name){
    var procs = (state.config && state.config.procedures) || {};
    var keys = Object.keys(procs);
    for(var i=0;i<keys.length;i++){ if((procs[keys[i]]||[]).indexOf(name)!==-1) return keys[i]; }
    return null;
  }

  // Groups every entry type (surgical, other, case, academic, seminar) by
  // calendar month so trainees and their supervisors can see logging pace
  // over time, not just lifetime totals -- sorted chronologically (oldest
  // first) so the bars read left-to-right as a timeline.
  function computeMonthlyTrend(entries){
    var months = {};
    entries.forEach(function(e){
      if(!e.date) return;
      var m = e.date.slice(0,7); // "YYYY-MM"
      if(!months[m]) months[m] = { month:m, total:0, surgical:0, other:0, "case":0, academic:0, seminar:0 };
      months[m].total++;
      var t = normType(e);
      if(months[m].hasOwnProperty(t)) months[m][t]++;
    });
    return Object.keys(months).sort().map(function(k){ return months[k]; });
  }
  function fmtMonthLabel(ym){
    try{ var d = new Date(ym+"-01T00:00:00"); return d.toLocaleDateString(undefined,{month:"short",year:"numeric"}); }
    catch(e){ return ym; }
  }
  function renderStatsAndCharts(entries){
    var s = computeStats(entries);
    var maxProc = s.procRows.length ? s.procRows[0].count : 0;
    var maxSite = s.siteRows.length ? s.siteRows[0].count : 0;
    var maxUnit = s.unitRows.length ? s.unitRows[0].count : 0;
    var trend = computeMonthlyTrend(entries);
    var maxTrend = trend.length ? Math.max.apply(null, trend.map(function(r){ return r.total; })) : 0;
    return ''+
    '<div class="stats-block"><h3>Total</h3><div class="stat-grid">'+
      statTile(s.total,"Total")+statTile(s.surgical,"Surgical","surgical")+statTile(s.other,"Other","other")+statTile(s["case"],"Cases","case")+statTile(s.academic,"Academic","academic")+statTile(s.seminar,"Seminars","seminar")+
    '</div></div>'+
    (trend.length ? '<div class="card stats-block"><h3>Time-based (entries per month, all types)</h3>'+
      trend.map(function(r){ return barRow(fmtMonthLabel(r.month), r.total, maxTrend, "var(--violet)"); }).join("")+
    '</div>' : '')+
    (s.siteRows.length ? '<div class="card stats-block"><h3>Area-wise (surgical + other procedures, by site)</h3>'+
      s.siteRows.map(function(r){ return barRow(catInfo(r.key).name, r.count, maxSite, catInfo(r.key).color, r.key); }).join("")+
    '</div>' : '')+
    (s.unitRows.length ? '<div class="card stats-block"><h3>Posting-wise (every entry type, by unit)</h3>'+
      s.unitRows.map(function(r){ return barRow(unitShort(r.key), r.count, maxUnit); }).join("")+
    '</div>' : '')+
    (s.procRows.length ? '<div class="card stats-block"><h3>Surgery-wise (procedures logged)</h3>'+
      s.procRows.map(function(r){ return barRow(r.name, r.count, maxProc, "var(--teal)", procedureCategoryKey(r.name)); }).join("")+
    '</div>' : '');
  }

  function renderScopeBanner(){
    var scope = state.consultantScope;
    if(!scope) return "";
    if(scope.full){
      var roles = scope.activeAssignments.filter(function(a){ return a.role==="hod"||a.role==="coordinator"; }).map(function(a){ return a.role==="hod" ? "Head of Department" : "Course Coordinator"; });
      return '<div class="notice-banner" style="background:var(--teal-bg); color:var(--teal-ink); border-color:var(--teal);">You currently have full access to every unit’s progress, as '+esc(roles.join(" & "))+'.</div>';
    }
    if(scope.units.length){
      return '<div class="notice-banner">You can currently see entries logged under: <b>'+scope.units.map(unitShort).join(", ")+'</b>.</div>';
    }
    return '<div class="notice-banner">Your account has no unit set yet, so no residents’ entries are visible to you. Ask your Developer admin to set your unit or appoint you Head of Unit / Course Coordinator / HOD.</div>';
  }

  /* ============================================================
     RENDER: RESIDENT - LOG ENTRY (picker + 4 single-step forms)
  ============================================================ */
  function renderResidentLog(){
    if(!state.wiz){
      return ''+
      '<div class="card">'+
        '<span class="eyebrow">What are you logging?</span>'+
        '<h2>Log a new entry</h2>'+
        '<p class="muted" style="margin:8px 0 16px;">Use the Hospital Number — never the patient’s name.</p>'+
        '<div class="cat-pick">'+
          '<div class="cat-card" data-start="surgical"><span class="icn" style="color:var(--teal);">'+icon("surgical")+'</span><div><div style="font-weight:600;">Surgical Procedure</div><div class="muted" style="font-size:12.5px;">Any OT-booked operative case.</div></div></div>'+
          '<div class="cat-card" data-start="other"><span class="icn" style="color:var(--amber);">'+icon("other")+'</span><div><div style="font-weight:600;">Other Procedure</div><div class="muted" style="font-size:12.5px;">OPD, bedside, ED or treatment-room procedures.</div></div></div>'+
          '<div class="cat-card" data-start="case"><span class="icn" style="color:var(--ink-soft);">'+icon("case")+'</span><div><div style="font-weight:600;">Interesting Case</div><div class="muted" style="font-size:12.5px;">Rare presentations, diagnostic dilemmas, teaching cases.</div></div></div>'+
          '<div class="cat-card" data-start="academic"><span class="icn" style="color:var(--green);">'+icon("academic")+'</span><div><div style="font-weight:600;">Academic Participation</div><div class="muted" style="font-size:12.5px;">CME, journal club, paper presentation, university activity.</div></div></div>'+
          '<div class="cat-card" data-start="seminar"><span class="icn" style="color:var(--violet);">'+icon("seminar")+'</span><div><div style="font-weight:600;">Seminar / Presentation</div><div class="muted" style="font-size:12.5px;">Seminars, lectures or case presentations YOU conducted.</div></div></div>'+
        '</div>'+
      '</div>';
    }
    if(state.wiz.entryType==="surgical") return renderSurgicalForm();
    if(state.wiz.entryType==="other") return renderOtherForm();
    if(state.wiz.entryType==="case") return renderCaseForm();
    if(state.wiz.entryType==="seminar") return renderSeminarForm();
    return renderAcademicForm();
  }

  // Alphabetical helpers used both when rendering pickers and when an admin
  // adds a new item to a config list, so a new addition lands in sorted
  // position instead of at the end (see addProcedure/addListItem/addUnit).
  // Deliberately NOT used for every list: roleLevels (an escalating
  // entrustment scale) and pgYears (JR-1/2/3) carry meaningful order that
  // alphabetizing would scramble, so those two stay in admin-defined/append
  // order everywhere they're read.
  function sortedStrings(arr){
    return (arr||[]).slice().sort(function(a,b){ return String(a).localeCompare(String(b), undefined, {sensitivity:"base"}); });
  }
  function sortedInsertIndex(arr, value){
    var i=0;
    while(i<arr.length && String(arr[i]).localeCompare(String(value), undefined, {sensitivity:"base"})<0) i++;
    return i;
  }
  function sortedByDisplayName(list){
    return (list||[]).slice().sort(function(a,b){ return String(a.displayName||"").localeCompare(String(b.displayName||""), undefined, {sensitivity:"base"}); });
  }

  // Searchable multi-select: same selection model and DOM contract as the
  // original checkbox-list multiPicker (.mp-box[data-mp-field], the
  // data-mp-add-input/-btn free-text escape hatch, chip-teal "extra" chips
  // for a selected value outside `options`) so every existing call site and
  // test keeps working — a live text filter (data-mp-search) is layered on
  // top, implemented as plain DOM show/hide in wireShellEvents rather than a
  // state change, so typing a search term never triggers a full re-render
  // and never costs the input its cursor position/focus.
  function multiPicker(fieldKey, options, selected){
    selected = selected || [];
    // Every current caller (diagnoses, comorbidities, per-site procedures,
    // assistants) is an unordered pool of choices where alphabetical is
    // strictly easier to scan than admin-add/API-fetch order -- sorted once,
    // here, rather than at each of the dozen call sites (and their tests'
    // hand-picked entries) so nothing can add a 13th call site that forgets
    // to sort.
    options = sortedStrings(options);
    var boxes = options.map(function(o){
      var checked = selected.indexOf(o)!==-1;
      return '<label class="mp-row" data-mp-row-text="'+esc(o.toLowerCase())+'" style="display:flex; gap:8px; align-items:center; font-size:13.5px; padding:4px 0;">'+
        '<input type="checkbox" class="mp-box" data-mp-field="'+esc(fieldKey)+'" value="'+esc(o)+'" '+(checked?"checked":"")+'> '+esc(o)+'</label>';
    }).join("");
    var extras = selected.filter(function(s){ return options.indexOf(s)===-1; });
    var extraChips = extras.map(function(s){
      return '<span class="chip chip-teal" style="margin:2px 4px 2px 0; display:inline-flex; align-items:center; gap:5px;">'+esc(s)+' <button type="button" data-mp-remove-extra="'+esc(fieldKey)+'" data-mp-extra-value="'+esc(s)+'" style="background:none;border:none;color:inherit;cursor:pointer;font-weight:700;padding:0;">×</button></span>';
    }).join("");
    // A short list (site, role levels, etc.) never reaches this function any
    // more -- those stayed plain selects -- but guard anyway rather than
    // assume every caller has already been updated.
    var showSearch = options.length > 6;
    return (showSearch ? '<input type="text" class="sp-search" data-mp-search="'+esc(fieldKey)+'" placeholder="Search…" autocomplete="off">' : '')+
      '<div class="mp-box-wrap" data-mp-list="'+esc(fieldKey)+'">'+(boxes||'<span class="muted" style="font-size:13px;">No options yet — add one below.</span>')+
      (showSearch ? '<div class="sp-empty-filter sp-row-hidden" data-mp-empty="'+esc(fieldKey)+'">No matches — add it below instead.</div>' : '')+
      '</div>'+
      (extraChips ? '<div style="margin-top:8px;">'+extraChips+'</div>' : '')+
      '<div style="display:flex; gap:8px; margin-top:8px;">'+
        '<input type="text" data-mp-add-input="'+esc(fieldKey)+'" placeholder="Add one not on the list…" style="flex:1;">'+
        '<button type="button" class="btn btn-sm" data-mp-add-btn="'+esc(fieldKey)+'">Add</button>'+
      '</div>';
  }

  // Searchable single-select: a text input that filters an always-rendered
  // list of choices (opened/closed purely by :focus-within in CSS, so it
  // needs no JS state). Selection writes into a real <input type="hidden">
  // carrying the given id, so every existing "read el(id).value at submit
  // time" call site (signup, admin create-user, postings) keeps working
  // completely unchanged -- this is a visual layer on top of that hidden
  // field, not a replacement for how its value gets read. `onSelectId`,
  // when given, additionally fires window.__entlog_ssPick's small dispatch
  // table for the few pickers (Consultant, a procedure block's Site) whose
  // value also needs to drive other reactive UI on selection.
  function searchSingleField(id, options, selectedValue, placeholder){
    // options: [{value, label, group?}], pre-sorted/pre-grouped by the
    // caller (see unitSearchOptions) -- a group header renders whenever an
    // option's group differs from the previous one.
    var selectedOpt = options.filter(function(o){ return o.value===selectedValue; })[0];
    var lastGroup, sawGroup=false;
    var rows = options.map(function(o){
      var groupHtml = "";
      if(o.group !== undefined){
        sawGroup = true;
        if(o.group !== lastGroup){ groupHtml = '<div class="ss-group-label">'+esc(o.group||"")+'</div>'; lastGroup = o.group; }
      }
      // mousedown (not click), with preventDefault, so selecting a row
      // never races the search input's own blur -- a plain onclick fires
      // only after the browser has already blurred the input (moving focus
      // is a mousedown-time default action), which closes the :focus-within
      // list before the click can land on it.
      return groupHtml+'<div class="ss-row'+(o.value===selectedValue?' ss-row-selected':'')+'" data-ss-row="'+esc(id)+'" data-ss-value="'+esc(o.value)+'" data-ss-label="'+esc(o.label)+'" data-ss-text="'+esc((o.label||"").toLowerCase())+'" onmousedown="event.preventDefault(); window.__entlog_ssPick(\''+esc(id)+'\', this.getAttribute(\'data-ss-value\'))">'+esc(o.label)+(o.value===selectedValue?' <span class="ss-check">✓</span>':'')+'</div>';
    }).join("");
    return '<div class="ss-wrap" data-ss-wrap="'+esc(id)+'">'+
      '<input type="hidden" id="'+esc(id)+'" value="'+esc(selectedValue||"")+'">'+
      '<input type="text" id="'+esc(id)+'-search" class="ss-search" data-ss-search="'+esc(id)+'" placeholder="'+esc(placeholder||"Search…")+'" value="'+esc(selectedOpt?selectedOpt.label:"")+'" autocomplete="off">'+
      '<div class="ss-list" data-ss-list="'+esc(id)+'">'+(rows||'<div class="sp-empty-filter">No options.</div>')+'</div>'+
    '</div>';
  }
  function ssRefreshVisual(id, value, label){
    var wrap = document.querySelector('[data-ss-wrap="'+id+'"]');
    if(!wrap) return;
    var hidden = document.getElementById(id);
    if(hidden) hidden.value = value||"";
    var search = wrap.querySelector('[data-ss-search]');
    if(search){ search.value = label||""; search.blur(); }
    wrap.querySelectorAll('[data-ss-row]').forEach(function(r){
      var isSel = r.getAttribute("data-ss-value")===value;
      r.classList.toggle("ss-row-selected", isSel);
      var check = r.querySelector(".ss-check");
      if(isSel && !check){ r.insertAdjacentHTML("beforeend", ' <span class="ss-check">✓</span>'); }
      if(!isSel && check){ check.remove(); }
    });
  }

  function consultantField(){
    var f = state.wiz.fields;
    var list = sortedByDisplayName(wizConsultantOptions());
    var options = list.map(function(c){ return { value:c.username, label:c.displayName }; });
    options.push({ value:"__other__", label:"Other / not listed" });
    return ''+
    '<div class="field"><label for="f-consultantChoice-search">Consultant</label>'+searchSingleField("f-consultantChoice", options, f.consultantChoice, "Search consultants…")+'</div>'+
    '<div class="field" id="consultant-other-wrap" style="'+(f.consultantChoice==="__other__"?"":"display:none;")+'"><label for="f-consultant-other">Consultant name</label><input id="f-consultant-other" type="text" value="'+esc(f.consultant||"")+'" placeholder="e.g. Dr. Rekha Menon"></div>';
  }

  // Shared by the Surgical and Other Procedure forms: one repeatable block
  // per site touched in this sitting -- a plain single site would have no
  // way to represent a genuine combined case (e.g. Ear+Nose in the same
  // sitting), each half of which can carry its own entrustment level (and,
  // for Surgical, its own laterality). `withLaterality` is false for Other
  // Procedure, which never had a laterality field.
  function renderProcedureBlocks(withLaterality){
    var f = state.wiz.fields;
    var blocks = f.procedureBlocks || [];
    var canRemove = blocks.length > 1;
    return blocks.map(function(block, idx){
      var procOptions = state.config.procedures[block.site] || [];
      // A 2+ block combined case gets a left accent stripe in that block's own
      // (muted) category color -- reinforces which fields belong to which
      // site at a glance, using color-coding that's already established
      // elsewhere (roster/table site chips) rather than inventing a new cue.
      var accent = blocks.length>1 ? ' border-left:3px solid '+catInfo(block.site).color+';' : '';
      return '<div class="card" style="background:var(--surface-2); margin-bottom:12px;'+accent+'">'+
        (blocks.length>1 ? '<div class="section-head" style="margin-bottom:8px;"><span class="muted" style="font-size:12px; text-transform:uppercase; letter-spacing:.04em;">Site '+(idx+1)+'</span>'+(canRemove?'<button type="button" class="btn btn-sm btn-danger" data-remove-block="'+idx+'">Remove this site</button>':'')+'</div>' : '')+
        '<div class="row2">'+
          '<div class="field"><label for="f-block-site-'+idx+'">Site</label><select id="f-block-site-'+idx+'" onchange="window.__entlog_setBlockSite('+idx+',this.value)">'+
            state.config.categories.map(function(c){ return '<option value="'+esc(c.key)+'" '+(c.key===block.site?"selected":"")+'>'+esc(c.name)+'</option>'; }).join("")+
          '</select></div>'+
          (withLaterality ?
            '<div class="field"><label for="f-block-laterality-'+idx+'">Side of procedure</label><select id="f-block-laterality-'+idx+'" onchange="window.__entlog_setBlockField('+idx+',\'laterality\',this.value)">'+opts_(state.config.laterality,block.laterality)+'</select></div>'
            :
            '<div class="field"><label for="f-block-role-'+idx+'">Your role (entrustment level)</label><select id="f-block-role-'+idx+'" onchange="window.__entlog_setBlockField('+idx+',\'role\',this.value)">'+opts_(state.config.roleLevels,block.role)+'</select></div>'
          )+
        '</div>'+
        '<div class="field"><label>Procedure(s) performed <span class="muted">(from '+esc(catInfo(block.site).name)+')</span></label>'+multiPicker("pb:"+idx+":procedures", procOptions, block.procedures)+'</div>'+
        (withLaterality ? '<div class="field"><label for="f-block-role-'+idx+'">Your role (entrustment level)</label><select id="f-block-role-'+idx+'" onchange="window.__entlog_setBlockField('+idx+',\'role\',this.value)">'+opts_(state.config.roleLevels,block.role)+'</select></div>' : '')+
      '</div>';
    }).join("")+
    '<button type="button" class="btn btn-sm" id="wiz-add-block" style="margin-bottom:14px;">+ Add another site / procedure (combined case)</button>';
  }

  function renderSurgicalForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Surgical Procedure</h2>'+
      '<div class="form-section"><div class="form-section-title">Patient &amp; procedure details</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-date">Date of procedure</label><input id="f-date" type="date" value="'+f.date+'" onchange="window.__entlog_wizDateChanged(this.value)"></div>'+
          '<div class="field"><label for="f-setting">Emergency / Elective</label><select id="f-setting">'+opts_(state.config.settings,f.setting)+'</select></div>'+
        '</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419"></div>'+
          '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
        '</div>'+
        '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Diagnoses &amp; comorbidities</div>'+
        '<div class="field"><label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses)+'</div>'+
        '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
        '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Sites &amp; procedures</div>'+
        renderProcedureBlocks(true)+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Consultant &amp; sign-off</div>'+
        consultantField()+
        '<div class="field"><label>Assistants <span class="muted">(optional)</span></label>'+multiPicker("assistantsPicked", wizPeopleDisplayNames(), f.assistantsPicked)+'</div>'+
        '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
        '<div class="field"><label for="f-caseReport">Will you be writing a case report?</label><select id="f-caseReport">'+opts_(["No","Yes"],f.caseReport)+'</select><div class="hint">Yes takes you straight into an Interesting Case entry, pre-filled with this case’s Hospital Number, age/sex, diagnoses, comorbidities and procedures.</div></div>'+
      '</div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save entry")+'</button></div>'+
    '</div>';
  }

  function renderOtherForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Other Procedure</h2>'+
      '<div class="form-section"><div class="form-section-title">Patient &amp; procedure details</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-otherSettingType">Setting</label><select id="f-otherSettingType">'+opts_(state.config.otherProcedureSettings,f.otherSettingType)+'</select></div>'+
          '<div class="field"><label for="f-date">Date of procedure</label><input id="f-date" type="date" value="'+f.date+'" onchange="window.__entlog_wizDateChanged(this.value)"></div>'+
        '</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-setting">Emergency / Elective</label><select id="f-setting">'+opts_(state.config.settings,f.setting)+'</select></div>'+
          '<div class="field"><label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419"></div>'+
        '</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
          '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
        '</div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Diagnoses &amp; comorbidities</div>'+
        '<div class="field"><label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses)+'</div>'+
        '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
        '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Sites &amp; procedures</div>'+
        renderProcedureBlocks(false)+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Consultant &amp; sign-off</div>'+
        consultantField()+
        '<div class="field"><label>Assistants <span class="muted">(optional)</span></label>'+multiPicker("assistantsPicked", wizPeopleDisplayNames(), f.assistantsPicked)+'</div>'+
        '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
      '</div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save entry")+'</button></div>'+
    '</div>';
  }

  function renderCaseForm(){
    var f = state.wiz.fields;
    var allProcs = [];
    Object.keys(state.config.procedures).forEach(function(k){ allProcs = allProcs.concat(state.config.procedures[k]); });
    return ''+
    '<div class="card">'+
      (state.wiz.linkedFromId ? '<div class="notice-banner" style="background:var(--teal-bg); color:var(--teal-ink); border-color:var(--teal);">Pre-filled from the surgical procedure you just logged — add the history and examination findings to finish.</div>' : '')+
      '<h2>'+(state.wiz.editingId?"Edit ":"")+'Interesting Case</h2>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419"></div>'+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+f.date+'"></div>'+
      '</div>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
        '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
      '</div>'+
      '<div class="field"><label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses)+'</div>'+
      '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
      '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '<div class="field"><label>Procedure(s) performed <span class="muted">(optional)</span></label>'+multiPicker("procedures", allProcs, f.procedures)+'</div>'+
      '<div class="field"><label for="f-history">Brief History</label><textarea id="f-history">'+esc(f.history||"")+'</textarea></div>'+
      '<div class="field"><label for="f-examination">Examination Findings</label><textarea id="f-examination">'+esc(f.examination||"")+'</textarea></div>'+
      '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save case")+'</button></div>'+
    '</div>';
  }

  function renderAcademicForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Academic Participation</h2>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+f.date+'"></div>'+
        '<div class="field"><label for="f-academicType">Type</label><select id="f-academicType" onchange="window.__entlog_toggleAcademicOther(this.value)">'+
          state.config.academicTypes.map(function(t){ return '<option '+(t===f.academicType?"selected":"")+'>'+esc(t)+'</option>'; }).join("")+
          '<option '+(f.academicType==="Other"?"selected":"")+'>Other</option>'+
        '</select></div>'+
      '</div>'+
      '<div class="field" id="academic-other-wrap" style="'+(f.academicType==="Other"?"":"display:none;")+'"><label for="f-academicTypeOther">Describe the activity type</label><input id="f-academicTypeOther" type="text" value="'+esc(f.academicTypeOther||"")+'"></div>'+
      '<div class="field"><label for="f-details">Details</label><textarea id="f-details" style="min-height:120px;">'+esc(f.details||"")+'</textarea></div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save activity")+'</button></div>'+
    '</div>';
  }

  function renderSeminarForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Seminar / Presentation</h2>'+
      '<p class="muted" style="margin-bottom:16px;">For seminars, lectures or case presentations <b>you</b> conducted — not ones you attended (log those as Academic Participation).</p>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+f.date+'"></div>'+
        '<div class="field"><label for="f-seminarType">Type</label><select id="f-seminarType" onchange="window.__entlog_toggleSeminarOther(this.value)">'+
          state.config.seminarTypes.map(function(t){ return '<option '+(t===f.seminarType?"selected":"")+'>'+esc(t)+'</option>'; }).join("")+
          '<option '+(f.seminarType==="Other"?"selected":"")+'>Other</option>'+
        '</select></div>'+
      '</div>'+
      '<div class="field" id="seminar-other-wrap" style="'+(f.seminarType==="Other"?"":"display:none;")+'"><label for="f-seminarTypeOther">Describe the activity type</label><input id="f-seminarTypeOther" type="text" value="'+esc(f.seminarTypeOther||"")+'"></div>'+
      '<div class="field"><label for="f-topic">Topic / Title</label><input id="f-topic" type="text" value="'+esc(f.topic||"")+'" placeholder="e.g. Approach to vertigo in primary care"></div>'+
      '<div class="field"><label for="f-venue">Venue / audience <span class="muted">(optional)</span></label><input id="f-venue" type="text" value="'+esc(f.venue||"")+'" placeholder="e.g. Departmental seminar, Unit 4"></div>'+
      '<div class="field"><label for="f-details">Details</label><textarea id="f-details" style="min-height:120px;">'+esc(f.details||"")+'</textarea></div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save activity")+'</button></div>'+
    '</div>';
  }

  /* ============================================================
     RENDER: RESIDENT - ENTRIES / PROGRESS / POSTINGS / ACCOUNT
  ============================================================ */
  // "Yes" is only meaningful on a Surgical Procedure entry that opted into a
  // case report; it's a clickable link straight to the Interesting Case entry
  // that was auto-created from it (see submitSurgical's case-report chain).
  function caseReportCell(r, rows){
    var t = normType(r);
    if(t==="surgical"){
      if(r.caseReport!=="Yes") return '<span class="case-no">No</span>';
      var linked = findLinkedCase(r.id, rows);
      if(linked) return '<button type="button" class="case-link" data-view-entry="'+esc(linked.id)+'">Yes</button>';
      return '<span class="case-no">Yes</span>';
    }
    // The reverse direction: a Case row that was itself created from (and
    // stays linked to) a surgical entry -- shown as a distinct "Linked"
    // indicator in the same column, clickable straight to that surgical
    // entry, so the connection is visible from either module without
    // needing a whole new column.
    if(t==="case" && r.linkedFromId){
      var origin = (rows||[]).filter(function(x){ return x.id===r.linkedFromId; })[0];
      if(origin) return '<button type="button" class="case-link case-link-origin" data-view-entry="'+esc(origin.id)+'">↩ Linked</button>';
      return '<span class="case-no">Linked</span>';
    }
    return '<span class="case-no">—</span>';
  }

  // The PG's own private write-up to-do for an Interesting Case linked to a
  // surgical entry -- backend only ever populates paperStatus for exactly
  // that combination (case + linkedFromId + resident author), so a plain
  // null/undefined check is enough to decide whether to show the control at
  // all; no need to re-derive the role/link rules client-side. Immediate
  // commit on change (like the multi-picker checkboxes elsewhere), sent as a
  // lightweight {paperStatus} PATCH -- safe now that update_entry() treats
  // an omitted field as "leave alone" rather than "clear it".
  var PAPER_STATUS_LABEL = { not_done: "Not started", in_progress: "In progress", done: "Done" };
  function paperStatusCell(r){
    if(r.paperStatus==null) return '<span class="case-no">—</span>';
    var opts = ["not_done","in_progress","done"].map(function(v){
      return '<option value="'+v+'"'+(r.paperStatus===v?' selected':'')+'>'+PAPER_STATUS_LABEL[v]+'</option>';
    }).join("");
    return '<select class="ps-select ps-'+esc(r.paperStatus)+'" data-paper-status="'+esc(r.id)+'" aria-label="Paper write-up status">'+opts+'</select>';
  }
  async function setPaperStatus(id, value){
    var entry = state.myEntries.filter(function(e){ return e.id==id; })[0];
    var prev = entry ? entry.paperStatus : null;
    if(entry) entry.paperStatus = value; // optimistic, so the select reflects the click immediately
    render();
    try{
      var updated = await dUpdateEntry(id, { paperStatus: value });
      if(entry) entry.paperStatus = updated.paperStatus;
      toast("Write-up status updated.");
    }catch(e){
      if(entry) entry.paperStatus = prev;
      toast("Could not update write-up status.");
    }
    render();
  }

  function renderResidentEntries(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var rows = state.myEntries.slice().sort(function(a,b){ return (b.date||"").localeCompare(a.date||""); });
    return ''+
    '<div class="card"><div class="section-head"><h2>My Entries ('+rows.length+')</h2><button class="btn btn-sm" id="export-my-entries">Export my entries (CSV)</button></div>'+
    '<div class="table-wrap cards-sm"><table><thead><tr>'+
      '<th>#</th><th>Date of entry</th><th>Date of procedure</th><th>Type</th><th>Hospital No.</th><th>Age/Sex</th>'+
      '<th>Procedure name</th><th>Primary diagnosis</th><th>Secondary diagnosis</th><th>Co-morbidities</th>'+
      '<th>Role</th><th>Consultant &amp; assistants</th><th>Case report</th><th>Write-up</th><th>Unit</th><th></th>'+
    '</tr></thead><tbody>'+
      (rows.length===0 ? '<tr><td colspan="16" data-label="" class="muted">Nothing logged yet.</td></tr>' : rows.map(function(r,i){
        return '<tr>'+
          '<td class="tabular" data-label="#">'+(i+1)+'</td>'+
          '<td class="tabular" data-label="Date of entry">'+fmtDate((r.createdAt||"").slice(0,10))+'</td>'+
          '<td class="tabular" data-label="Date of procedure">'+fmtDate(r.date)+'</td>'+
          '<td data-label="Type">'+entryTypeChip(r)+'</td>'+
          '<td data-label="Hospital No.">'+esc(entryHospitalNumber(r)||"—")+'</td>'+
          '<td class="tabular" data-label="Age/Sex">'+esc(entryAgeSex(r))+'</td>'+
          '<td data-label="Procedure name">'+esc(summarizeEntry(r))+'</td>'+
          '<td data-label="Primary diagnosis">'+esc(entryDiagnoses(r).join(", ")||"—")+'</td>'+
          '<td data-label="Secondary diagnosis">'+esc(entrySecondaryDiagnoses(r).join(", ")||"—")+'</td>'+
          '<td data-label="Co-morbidities">'+esc(entryComorbidities(r).join(", ")||"—")+'</td>'+
          '<td data-label="Role">'+esc(entryRoleSummary(r)||"—")+'</td>'+
          '<td data-label="Consultant &amp; assistants">'+entryConsultantAndAssistants(r)+'</td>'+
          '<td data-label="Case report">'+caseReportCell(r, rows)+'</td>'+
          '<td data-label="Write-up">'+paperStatusCell(r)+'</td>'+
          '<td data-label="Unit">'+unitShortHtml(r.unit)+'</td>'+
          '<td data-label="" style="white-space:nowrap;"><button class="btn btn-sm" data-view-entry="'+r.id+'">View</button> <button class="btn btn-sm" data-edit-entry="'+r.id+'">Edit</button> <button class="btn btn-sm" data-view-history="'+r.id+'">History</button> <button class="btn btn-sm btn-danger" data-del="'+r.id+'">Delete</button></td>'+
        '</tr>';
      }).join(""))+
    '</tbody></table></div></div>';
  }

  function renderEntryDetailModal(){
    var e = findEntryById(state.viewingEntryId);
    if(!e) return "";
    var t = normType(e);
    var rows = [];
    rows.push(["Type", entryTypeChip(e)]);
    rows.push(["Date", fmtDate(e.date)]);
    if(entryHospitalNumber(e)) rows.push(["Hospital Number", esc(entryHospitalNumber(e))]);
    if(e.age || e.sex) rows.push(["Age/Sex", esc(entryAgeSex(e))]);
    if(t==="surgical" || t==="other" || t==="case"){
      if(entryDiagnoses(e).length) rows.push(["Primary diagnosis", esc(entryDiagnoses(e).join(", "))]);
      if(entrySecondaryDiagnoses(e).length) rows.push(["Secondary diagnosis", esc(entrySecondaryDiagnoses(e).join(", "))]);
      if(entryComorbidities(e).length) rows.push(["Co-morbidities", esc(entryComorbidities(e).join(", "))]);
    }
    if(t==="surgical" || t==="other"){
      // One row per site/procedure block rather than a single flattened
      // "Procedure(s)"/"Role" pair -- a combined multi-site case has a
      // different role/laterality per site, which a flattened view can't
      // represent.
      entryProcedureBlocks(e).forEach(function(b){
        var bits = [(b.procedures||[]).join(", ")||"—"];
        if(b.laterality) bits.push(b.laterality);
        if(b.role) bits.push(b.role);
        rows.push([catInfo(b.site).name, esc(bits.join(" · "))]);
      });
    } else if(entryProcedures(e).length){
      rows.push(["Procedure(s)", esc(entryProcedures(e).join(", "))]);
    }
    if(t==="case"){
      rows.push(["Brief History", esc(e.history||"—")]);
      rows.push(["Examination Findings", esc(e.examination||"—")]);
    }
    if(t!=="surgical" && t!=="other" && e.role) rows.push(["Role", esc(e.role)]);
    if(e.consultant) rows.push(["Consultant", esc(e.consultant)]);
    if(e.assistants) rows.push(["Assistants", esc(e.assistants)]);
    if(e.comments) rows.push(["Comments/Complications", esc(e.comments)]);
    if(t==="seminar"){
      rows.push(["Activity type", esc((e.seminarType==="Other"?e.seminarTypeOther:e.seminarType)||"—")]);
      rows.push(["Topic", esc(e.topic||"—")]);
      if(e.venue) rows.push(["Venue", esc(e.venue)]);
      rows.push(["Details", esc(e.details||"—")]);
    }
    if(t==="academic"){
      rows.push(["Activity type", esc((e.academicType==="Other"?e.academicTypeOther:e.academicType)||"—")]);
      rows.push(["Details", esc(e.details||"—")]);
    }
    if(e.unit) rows.push(["Unit", unitShortHtml(e.unit)]);
    return '<div class="modal-overlay" id="entry-detail-overlay">'+
      '<div class="modal-card">'+
        '<button class="modal-close" id="entry-detail-close" aria-label="Close">×</button>'+
        '<span class="eyebrow">Entry detail</span>'+
        '<h2>'+(t==="case"?"Interesting Case":esc(summarizeEntry(e)))+'</h2>'+
        '<div style="margin-top:14px;">'+
          rows.map(function(r){ return '<div class="detail-row"><div class="k">'+esc(r[0])+'</div><div>'+r[1]+'</div></div>'; }).join("")+
        '</div>'+
      '</div>'+
    '</div>';
  }

  // Edit history: who changed what, when. GET /entries/<id>/history already
  // enforces who's allowed to see it (author, Developer, HOD, Coordinator, or
  // a Head of Unit within their unit scope) -- the frontend just renders
  // whatever comes back, or a plain access message on a 403.
  var HISTORY_FIELD_LABELS = {
    entryType:"Type", unit:"Unit", date:"Date of procedure", site:"Site", procedures:"Procedure(s)",
    setting:"Setting", otherSettingType:"Setting detail", hospitalNumber:"Hospital Number",
    age:"Age", sex:"Sex", diagnoses:"Primary diagnosis", diagnosesSecondary:"Secondary diagnosis",
    comorbidities:"Co-morbidities", laterality:"Laterality", role:"Role", consultant:"Consultant",
    consultantUsername:"Consultant (linked account)", assistants:"Assistants", comments:"Comments/Complications",
    caseReport:"Case report?", linkedFromId:"Linked entry ID", history:"Brief History", examination:"Examination Findings",
    academicType:"Activity type", academicTypeOther:"Activity type (other)", seminarType:"Seminar type",
    seminarTypeOther:"Seminar type (other)", topic:"Topic", venue:"Venue", details:"Details", paperStatus:"Write-up status",
    procedureBlocks:"Sites & procedures"
  };
  function historyFieldLabel(k){ return HISTORY_FIELD_LABELS[k] || k; }
  function historyBlockValue(b){
    var bits = [(b.procedures||[]).join(", ")||"—"];
    if(b.laterality) bits.push(b.laterality);
    if(b.role) bits.push(b.role);
    return esc(catInfo(b.site).name) + ": " + esc(bits.join(" · "));
  }
  function historyFieldValue(v){
    if(v==null || v==="") return '<span class="muted">—</span>';
    if(Array.isArray(v)){
      if(!v.length) return '<span class="muted">—</span>';
      // A procedureBlocks array is objects, not plain strings -- format each
      // block on its own line rather than falling through to the plain
      // join() below (which would print "[object Object]").
      if(typeof v[0]==="object" && v[0]!==null && "site" in v[0]){
        return v.map(historyBlockValue).join("<br>");
      }
      return esc(v.join(", "));
    }
    if(typeof v==="object") return esc(JSON.stringify(v));
    return esc(String(v));
  }
  async function openEntryHistory(id){
    state.viewingHistoryEntryId = id;
    state.historyLoading = true;
    state.historyEdits = [];
    state.historyError = "";
    render();
    try{
      state.historyEdits = await dGetEntryHistory(id);
    }catch(e){
      state.historyError = "You don't have access to this entry's history.";
    }
    state.historyLoading = false;
    render();
  }
  function renderEntryHistoryModal(){
    if(state.viewingHistoryEntryId==null) return "";
    var body;
    if(state.historyLoading){
      body = '<div class="empty-state">Loading…</div>';
    } else if(state.historyError){
      body = '<div class="empty-state">'+esc(state.historyError)+'</div>';
    } else if(state.historyEdits.length===0){
      body = '<div class="empty-state">No edits recorded yet — this entry hasn’t changed since it was created.</div>';
    } else {
      body = state.historyEdits.slice().reverse().map(function(ed){
        var fields = Object.keys(ed.changes||{});
        return '<div class="history-entry">'+
          '<div class="history-entry-head"><b>'+esc(ed.editedBy)+'</b> <span class="muted tabular">'+fmtDateTime(ed.editedAt)+'</span></div>'+
          '<div class="history-changes">'+
            fields.map(function(f){
              var c = ed.changes[f];
              return '<div class="detail-row"><div class="k">'+esc(historyFieldLabel(f))+'</div><div>'+historyFieldValue(c.old)+' → '+historyFieldValue(c.new)+'</div></div>';
            }).join("")+
          '</div>'+
        '</div>';
      }).join("");
    }
    return '<div class="modal-overlay" id="entry-history-overlay">'+
      '<div class="modal-card">'+
        '<button class="modal-close" id="entry-history-close" aria-label="Close">×</button>'+
        '<span class="eyebrow">Edit history</span>'+
        '<h2>Entry #'+esc(state.viewingHistoryEntryId)+'</h2>'+
        '<div style="margin-top:14px;">'+body+'</div>'+
      '</div>'+
    '</div>';
  }

  function renderResidentProgress(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    return renderStatsAndCharts(state.myEntries);
  }

  function renderResidentPostings(){
    var postings = (state.user.postings||[]).map(function(p,i){ return {p:p, origIndex:i}; });
    postings.sort(function(a,b){ return (b.p.startDate||"").localeCompare(a.p.startDate||""); });
    var todayStr = todayISO();
    var currentShown = false;
    var rows = postings.map(function(entry){
      var p = entry.p;
      var isCurrent = !currentShown && p.startDate<=todayStr && (!p.endDate || p.endDate>=todayStr);
      if(isCurrent) currentShown = true;
      return '<tr><td class="tabular">'+fmtDate(p.startDate)+'</td><td class="tabular">'+(p.endDate?fmtDate(p.endDate):'<span class="muted">Ongoing</span>')+'</td><td>'+unitShortHtml(p.unit)+' <span class="muted">'+esc(unitFull(p.unit))+'</span>'+(isCurrent?' <span class="chip chip-green">Current</span>':'')+'</td><td><button class="btn btn-sm" data-remove-posting="'+entry.origIndex+'">Remove</button></td></tr>';
    }).join("");
    return ''+
    '<div class="card"><h2>My unit postings</h2>'+
      '<p class="muted" style="margin-bottom:16px;">Log each posting with its start (and, once you know it, end) date — every entry you log automatically picks up whichever posting was active on that entry’s date, so your history stays accurate as you rotate through units.</p>'+
      (rows ? '<div class="table-wrap"><table><thead><tr><th>Start date</th><th>End date</th><th>Unit</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>' : '<p class="muted" style="font-size:13px;">No postings logged yet — add your current one below.</p>')+
      '<div class="row3" style="margin-top:16px;">'+
        '<div class="field"><label for="posting-unit-search">Unit</label>'+searchSingleField("posting-unit", unitSearchOptions(), null, "Search units…")+'</div>'+
        '<div class="field"><label for="posting-date">Start date</label><input id="posting-date" type="date" value="'+todayStr+'"></div>'+
        '<div class="field"><label for="posting-end">End date <span class="muted">(optional — leave blank if ongoing)</span></label><input id="posting-end" type="date"></div>'+
      '</div>'+
      '<button class="btn btn-primary" id="add-posting">Add posting</button>'+
    '</div>';
  }

  function renderMyAccount(){
    return ''+
    '<div class="card"><h2>Change password</h2>'+
      '<div class="field"><label for="pw-old">Current password</label><input id="pw-old" type="password"></div>'+
      '<div class="row2">'+
        '<div class="field"><label for="pw-new">New password</label><input id="pw-new" type="password"></div>'+
        '<div class="field"><label for="pw-confirm">Confirm new password</label><input id="pw-confirm" type="password"></div>'+
      '</div>'+
      '<button class="btn btn-primary" id="btn-change-password">Update password</button>'+
    '</div>'+
    '<div class="card"><h2 style="font-size:15px;">Forgot it entirely?</h2>'+
      '<p class="muted">If you’re locked out, sign out and use “Forgot your password?” on the sign-in screen — your Developer admin will set a new one for you.</p>'+
    '</div>';
  }

  /* ============================================================
     RENDER: CONSULTANT
  ============================================================ */
  function renderConsultantRoster(){
    if(state.loading) return '<div class="empty-state">Loading roster…</div>';
    var banner = renderScopeBanner();
    if(state.roster.length===0) return banner+'<div class="card"><div class="empty-state">No trainees’ entries are visible to you right now.</div></div>';
    return banner+''+
    '<div class="card"><div class="section-head"><h2>Trainee roster</h2><button class="btn btn-sm" id="export-my-entries">Export visible entries (CSV)</button></div>'+
    '<div class="table-wrap"><table><thead><tr><th>Trainee</th><th>Role</th><th>Batch</th><th>Current unit</th><th>Total</th><th>Surgical</th><th>Other</th><th>Cases</th><th>Academic</th><th>Seminars</th><th>Last entry</th><th></th></tr></thead><tbody>'+
      state.roster.map(function(r){
        var s = computeStats(r.entries);
        var last = r.entries.map(function(e){return e.date;}).sort().slice(-1)[0];
        var currentUnit = unitForDate(r.user.postings, todayISO());
        return '<tr><td>'+esc(r.user.displayName)+'</td><td><span class="chip chip-grey">'+esc(roleLabel(r.user.role))+'</span></td><td>'+esc(r.user.pgYear||"—")+'</td><td>'+(currentUnit?unitShortHtml(currentUnit):"—")+'</td><td class="tabular">'+s.total+'</td><td class="tabular">'+s.surgical+'</td><td class="tabular">'+s.other+'</td><td class="tabular">'+s["case"]+'</td><td class="tabular">'+s.academic+'</td><td class="tabular">'+s.seminar+'</td><td class="tabular">'+fmtDate(last)+'</td><td><button class="btn btn-sm" data-view-resident="'+esc(r.user.username)+'">View</button></td></tr>';
      }).join("")+
    '</tbody></table></div></div>';
  }

  function renderConsultantDetail(){
    if(!state.detailUser){ return '<div class="empty-state">Loading…</div>'; }
    var entries = state.detailEntries.slice().sort(function(a,b){ return (b.date||"").localeCompare(a.date||""); });
    // Edit-history affordance for supervisors: only Head of Unit/HOD/Coordinator
    // (the same set the backend's GET /entries/<id>/history actually allows,
    // per the "visible to ... Head of unit, HOD and developer" + Coordinator
    // clarification) -- a plain Professor with roster access but no role
    // assignment sees the entries themselves but never gets this button.
    var caps = state.capabilities || {};
    var showHistory = !!(caps.isHod || caps.isCoordinator || caps.isHeadOfUnit);
    return ''+
    renderScopeBanner()+
    '<button class="btn btn-sm" id="back-to-roster" style="margin-bottom:14px;">← Back to roster</button>'+
    '<div class="card"><h2>'+esc(state.detailUser.displayName)+'</h2><p class="muted">'+esc(state.detailUser.pgYear||"")+'</p></div>'+
    renderStatsAndCharts(entries)+
    '<div class="card"><h2>Entries ('+entries.length+')</h2>'+
    '<div class="table-wrap cards-sm"><table><thead><tr><th>Date</th><th>Type</th><th>Hospital No.</th><th>Age/Sex</th><th>Summary</th><th>Unit</th><th>Role</th><th>Case report</th>'+(showHistory?'<th></th>':'')+'</tr></thead><tbody>'+
      (entries.length===0 ? '<tr><td colspan="'+(showHistory?9:8)+'" data-label="" class="muted">No entries visible to you.</td></tr>' : entries.map(function(r){
        return '<tr><td class="tabular" data-label="Date">'+fmtDate(r.date)+'</td><td data-label="Type">'+entryTypeChip(r)+'</td><td data-label="Hospital No.">'+esc(entryHospitalNumber(r)||"—")+'</td><td class="tabular" data-label="Age/Sex">'+esc(entryAgeSex(r))+'</td><td data-label="Summary">'+esc(summarizeEntry(r))+'</td><td data-label="Unit">'+unitShortHtml(r.unit)+'</td><td data-label="Role">'+esc(entryRoleSummary(r)||"—")+'</td><td data-label="Case report">'+caseReportCell(r, entries)+'</td>'+(showHistory?'<td data-label=""><button class="btn btn-sm" data-view-history="'+r.id+'">History</button></td>':'')+'</tr>';
      }).join(""))+
    '</tbody></table></div></div>';
  }

  /* ============================================================
     RENDER: DEVELOPER
  ============================================================ */
  function renderCreateUserForm(){
    var role = state.newUserRole || "resident";
    return ''+
    '<div class="card">'+
      '<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:'+(state.showCreateUserForm?"14px":"0")+';">'+
        '<h2 style="margin-bottom:0;">Create an account directly</h2>'+
        '<button class="btn btn-sm" id="toggle-create-user">'+(state.showCreateUserForm?"Cancel":"+ New account")+'</button>'+
      '</div>'+
      (state.showCreateUserForm ? (
        '<p class="muted" style="margin-bottom:14px;">This is in addition to open sign-up — use it to hand someone a ready-made login instead of waiting for them to register themselves.</p>'+
        '<div class="field"><label>Role</label><div class="radio-group">'+
          radioCard("newuser-role","resident",role==="resident","PG Resident","")+
          radioCard("newuser-role","senior_resident",role==="senior_resident","Senior Resident","")+
          radioCard("newuser-role","fellow",role==="fellow","Fellow","")+
          radioCard("newuser-role","consultant",role==="consultant","Consultant / Faculty","")+
          radioCard("newuser-role","developer",role==="developer","Developer","")+
        '</div></div>'+
        '<div class="row2">'+
          '<div class="field"><label for="nu-username">Username</label><input id="nu-username" type="text"></div>'+
          '<div class="field"><label for="nu-password">Temporary password</label><input id="nu-password" type="text"></div>'+
        '</div>'+
        '<div class="field"><label for="nu-displayName">Display name</label><input id="nu-displayName" type="text"></div>'+
        (isTraineeRole(role) ? '<div class="field"><label for="nu-pgYear">Batch / Year</label><select id="nu-pgYear">'+opts_(state.config.pgYears,state.config.pgYears[0])+'</select></div>' : '')+
        (role==="consultant" ? (
          '<div class="row2">'+
            '<div class="field"><label for="nu-designation">Designation</label><select id="nu-designation">'+opts_(state.config.consultantDesignations, state.config.consultantDesignations[0])+'</select></div>'+
            '<div class="field"><label for="nu-unit-search">Home unit</label>'+searchSingleField("nu-unit", unitSearchOptions(), null, "Search units…")+'</div>'+
          '</div>'
        ) : '')+
        (role==="fellow" ? '<div class="field"><label for="nu-unit-search">Parent / home unit</label>'+searchSingleField("nu-unit", unitSearchOptions(), null, "Search units…")+'</div>' : '')+
        '<button class="btn btn-primary" id="submit-create-user">Create account</button>'
      ) : '')+
    '</div>';
  }

  // Shared account-row renderer for both the Developer "All accounts" table
  // and the HOD/Coordinator/Head-of-Unit "Manage accounts" table. `canChangeRole`
  // gates the role dropdown (Developer only, per spec); the batch/designation
  // inline edit and deactivate/delete controls are available to both, since
  // canManageProfiles already restricts who reaches this table at all.
  function userAccountRow(u, canChangeRole){
    var statusChip = u.active===false ? '<span class="chip chip-red">Deactivated</span>' : '<span class="chip chip-green">Active</span>';
    var roleCell = canChangeRole ?
      ('<select data-role-select="'+esc(u.username)+'" style="padding:5px 7px; font-size:12.5px;">'+
        ["resident","senior_resident","fellow","consultant","developer"].map(function(r){ return '<option value="'+r+'" '+(r===u.role?"selected":"")+'>'+esc(roleLabel(r))+'</option>'; }).join("")+
      '</select> <button class="btn btn-sm" data-apply-role="'+esc(u.username)+'">Apply</button>')
      : '<span class="chip chip-grey">'+esc(roleLabel(u.role))+'</span>';
    // A Fellow gets TWO inline-editable fields (batch AND parent unit) where
    // every other role gets at most one, so each control's select is scoped
    // by username+field ("user|field") rather than username alone -- picking
    // the right one when a row has more than one Save button.
    var profileParts = [];
    if(isTraineeRole(u.role)){
      profileParts.push(
        '<div'+(u.role==="fellow"?' style="margin-bottom:4px;"':'')+'><select data-profile-select="'+esc(u.username)+'|pgYear" style="padding:5px 7px; font-size:12.5px;">'+opts_(state.config.pgYears, u.pgYear)+'</select> '+
        '<button class="btn btn-sm" data-apply-profile="'+esc(u.username)+'" data-profile-field="pgYear">Save</button></div>'
      );
    }
    if(u.role==="fellow"){
      profileParts.push(
        '<div><select data-profile-select="'+esc(u.username)+'|unit" style="padding:5px 7px; font-size:12.5px;">'+unitOptions(u.unit)+'</select> '+
        '<button class="btn btn-sm" data-apply-profile="'+esc(u.username)+'" data-profile-field="unit">Save</button></div>'
      );
    }
    if(u.role==="consultant"){
      profileParts.push(
        '<select data-profile-select="'+esc(u.username)+'|designation" style="padding:5px 7px; font-size:12.5px;">'+opts_(state.config.consultantDesignations, u.designation)+'</select> '+
        '<button class="btn btn-sm" data-apply-profile="'+esc(u.username)+'" data-profile-field="designation">Save</button>'
      );
    }
    var profileCell = profileParts.length ? profileParts.join("") : "—";
    return '<tr><td class="mono">'+esc(u.username)+'</td><td>'+esc(u.displayName)+'</td><td>'+roleCell+'</td><td>'+profileCell+'</td><td>'+statusChip+'</td>'+
      '<td style="white-space:nowrap;">'+
        '<button class="btn btn-sm '+(u.active===false?"":"btn-danger")+'" data-toggle-active="'+esc(u.username)+'" data-next="'+(u.active===false?"true":"false")+'">'+(u.active===false?"Reactivate":"Deactivate")+'</button> '+
        '<button class="btn btn-sm btn-danger" data-delete-user="'+esc(u.username)+'">Delete</button>'+
      '</td></tr>';
  }
  function renderUserAccountsTable(rows, canChangeRole){
    return '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Batch / Designation / Unit</th><th>Status</th><th></th></tr></thead><tbody>'+
      rows.map(function(u){ return userAccountRow(u, canChangeRole); }).join("")+
    '</tbody></table></div>';
  }

  function renderDeveloperUsers(){
    if(state.loading) return '<div class="empty-state">Loading users…</div>';
    var rows = state.devUsers.slice().sort(function(a,b){ return (a.username).localeCompare(b.username); });
    return ''+
    renderCreateUserForm()+
    '<div class="card"><h2>All accounts ('+rows.length+')</h2>'+
    renderUserAccountsTable(rows, true)+
    '</div>';
  }

  function renderManageUsers(){
    if(state.loading) return '<div class="empty-state">Loading accounts…</div>';
    var rows = state.manageUsers.slice().sort(function(a,b){ return (a.username).localeCompare(b.username); });
    return ''+
    '<div class="card"><h2>Manage accounts ('+rows.length+')</h2>'+
      '<p class="muted" style="margin-bottom:14px;">Update a trainee’s batch as they progress, or a consultant’s designation on promotion, and deactivate or delete accounts that no longer need access. Role changes and password resets stay Developer-only.</p>'+
      renderUserAccountsTable(rows, false)+
    '</div>';
  }

  function renderSignupApprovals(){
    if(state.loading) return '<div class="empty-state">Loading sign-up requests…</div>';
    var rows = state.signupRequests.slice().sort(function(a,b){ return (a.createdAt||"").localeCompare(b.createdAt||""); });
    return ''+
    '<div class="card"><h2>Pending sign-ups ('+rows.length+')</h2>'+
      '<p class="muted" style="margin-bottom:14px;">New accounts wait here until someone eligible approves them — approving lets them sign in right away; rejecting deletes the request outright.</p>'+
      (rows.length===0 ? '<div class="empty-state">Nothing waiting on you.</div>' :
      '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Batch / Designation</th><th>Unit</th><th>Requested</th><th></th></tr></thead><tbody>'+
        rows.map(function(u){
          return '<tr><td class="mono">'+esc(u.username)+'</td><td>'+esc(u.displayName)+'</td><td><span class="chip chip-grey">'+esc(roleLabel(u.role))+'</span></td>'+
          '<td>'+esc(u.pgYear || u.designation || "—")+'</td><td>'+unitShortHtml(u.unit)+'</td><td class="tabular">'+fmtDateTime(u.createdAt)+'</td>'+
          '<td style="white-space:nowrap;"><button class="btn btn-sm btn-primary" data-approve-signup="'+esc(u.username)+'">Approve</button> <button class="btn btn-sm btn-danger" data-reject-signup="'+esc(u.username)+'">Reject</button></td></tr>';
        }).join("")+
      '</tbody></table></div>')+
    '</div>';
  }

  function renderDeveloperPasswordRequests(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var rows = state.passwordResets.slice().sort(function(a,b){ return (b.requestedAt||"").localeCompare(a.requestedAt||""); });
    var pending = rows.filter(function(r){ return r.status==="pending"; });
    var resolved = rows.filter(function(r){ return r.status!=="pending"; });
    function reqRow(r, isPending){
      var u = state.devUsers.filter(function(x){ return x.username===r.username; })[0];
      return '<tr><td class="mono">'+esc(r.username)+'</td><td>'+esc(u?u.displayName:"—")+'</td><td>'+esc(r.note||"—")+'</td><td class="tabular">'+fmtDateTime(r.requestedAt)+'</td>'+
        (isPending ?
          '<td><input type="text" placeholder="New password" style="width:140px; display:inline-block;" data-pw-input="'+r.id+'"> <button class="btn btn-sm btn-primary" data-resolve-request="'+r.id+'" data-resolve-username="'+esc(r.username)+'">Set & resolve</button></td>'
          : '<td><span class="chip chip-grey">Resolved</span></td>')+
      '</tr>';
    }
    return ''+
    '<div class="card"><h2>Pending requests ('+pending.length+')</h2>'+
      (pending.length===0 ? '<p class="muted" style="font-size:13px;">Nothing waiting.</p>' :
      '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Note</th><th>Requested</th><th></th></tr></thead><tbody>'+pending.map(function(r){return reqRow(r,true);}).join("")+'</tbody></table></div>')+
    '</div>'+
    (resolved.length ? '<div class="card"><h2 style="font-size:15px;">Resolved</h2>'+
      '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Note</th><th>Requested</th><th></th></tr></thead><tbody>'+resolved.map(function(r){return reqRow(r,false);}).join("")+'</tbody></table></div>'+
    '</div>' : '');
  }

  function renderDeveloperData(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var traineeCount = state.devUsers.filter(function(u){return isTraineeRole(u.role);}).length;
    var consultantCount = state.devUsers.filter(function(u){return u.role==="consultant";}).length;
    var devCount = state.devUsers.filter(function(u){return u.role==="developer";}).length;
    return ''+
    '<div class="stat-grid">'+
      statTile(state.devAllEntries.length,"Total entries")+
      statTile(traineeCount,"Trainees")+
      statTile(consultantCount,"Consultants")+
      statTile(devCount,"Developers")+
    '</div>'+
    '<div class="card"><h2>Export (your “local copy”)</h2>'+
      '<p class="muted" style="margin-bottom:14px;">This platform stores data server-side for the group; export a CSV whenever you want a local, offline copy — for backup, for Excel-side analysis, or before big changes.</p>'+
      '<div style="display:flex; gap:10px; flex-wrap:wrap;">'+
        '<button class="btn btn-primary" id="export-entries">Export all entries (CSV)</button>'+
        '<button class="btn" id="export-users">Export all users (CSV)</button>'+
      '</div>'+
    '</div>'+
    '<div class="card"><h2 style="color:var(--amber);">Backups</h2>'+
      '<p class="muted">The database is a single SQLite file on the server’s disk — there is no size ceiling built into the app, but there’s also no automatic off-site backup. Export a CSV regularly, and make sure whoever hosts this schedules real backups of the data file (see the deployment README).</p>'+
    '</div>';
  }

  /* ============================================================
     RENDER: DEVELOPER - MANAGE LISTS
  ============================================================ */
  function renderDeveloperLists(){
    var cats = state.config.categories;
    if(!state.devListDraft.selectedCat && cats.length) state.devListDraft.selectedCat = cats[0].key;
    var selKey = state.devListDraft.selectedCat;
    var selCat = cats.filter(function(c){ return c.key===selKey; })[0];
    var procList = selCat ? (state.config.procedures[selCat.key]||[]) : [];

    var catRows = cats.map(function(c){
      return '<div class="cat-card" style="cursor:default; align-items:center;" data-cat-row="'+esc(c.key)+'">'+
        '<input type="color" data-cat-color="'+esc(c.key)+'" value="'+toHexColor(c.color)+'" style="width:28px; height:28px; border:none; padding:0; border-radius:6px; cursor:pointer;">'+
        '<input type="text" data-cat-name="'+esc(c.key)+'" value="'+esc(c.name)+'" style="flex:1; border:1px solid var(--line); border-radius:8px; padding:7px 9px; font-size:13.5px;">'+
        '<button class="btn btn-sm" data-cat-select="'+esc(c.key)+'" style="'+(selKey===c.key?"border-color:var(--teal); color:var(--teal-ink);":"")+'">Edit list ('+((state.config.procedures[c.key]||[]).length)+')</button>'+
        '<button class="btn btn-sm btn-danger" data-cat-remove="'+esc(c.key)+'">Remove</button>'+
      '</div>';
    }).join("");

    // Alphabetized for display regardless of storage order, so a list that
    // predates this change (or was seeded from DEFAULT_PROCEDURES) shows
    // sorted immediately rather than only once every item has been
    // individually re-added -- remove is by value (see removeProcedure) so
    // display order never has to match storage order for this to be safe.
    var procRows = sortedStrings(procList).map(function(p){
      return '<div class="proc-opt" style="display:flex; align-items:center; justify-content:space-between; gap:10px; cursor:default;"><span>'+esc(p)+'</span><button class="btn btn-sm btn-danger" data-proc-remove="'+esc(p)+'">Remove</button></div>';
    }).join("") || '<p class="muted" style="font-size:13px;">No procedures in this site yet — add the first one below.</p>';

    var simpleSections = SIMPLE_LISTS.map(function(spec){
      var items = state.config[spec.key] || [];
      var displayItems = spec.sortable ? sortedStrings(items) : items;
      var rows = displayItems.map(function(v,i){
        var removeKey = spec.sortable ? esc(v) : i;
        return '<div class="proc-opt" style="display:flex; align-items:center; justify-content:space-between; gap:10px; cursor:default;"><span>'+esc(v)+'</span><button class="btn btn-sm btn-danger" data-simple-remove="'+spec.key+'" data-idx="'+removeKey+'">Remove</button></div>';
      }).join("");
      return '<div class="card">'+
        '<h2 style="font-size:15px;">'+esc(spec.title)+'</h2>'+
        '<p class="muted" style="font-size:12.5px; margin-top:-8px; margin-bottom:12px;">'+esc(spec.hint)+'</p>'+
        '<div style="display:flex; flex-direction:column; gap:6px; margin-bottom:10px;">'+rows+'</div>'+
        '<div style="display:flex; gap:8px;">'+
          '<input type="text" id="newitem-'+spec.key+'" placeholder="Add an option…" style="flex:1;">'+
          '<button class="btn btn-sm btn-primary" data-simple-add="'+spec.key+'">Add</button>'+
        '</div>'+
      '</div>';
    }).join("");

    return ''+
    '<div class="card"><h2>Sites & procedures</h2>'+
      '<p class="muted" style="margin-bottom:14px;">This is what residents see, in order, when logging a Surgical or Other Procedure entry’s Site field. Edit a name or colour and it saves as you leave the field; use “Edit list” to add or remove the procedures inside a site.</p>'+
      '<div style="display:flex; flex-direction:column; gap:8px; margin-bottom:16px;">'+catRows+'</div>'+
      '<div style="display:flex; gap:8px; border-top:1px dashed var(--line); padding-top:14px;">'+
        '<input type="color" id="newcat-color" value="#0F6B72" style="width:34px; height:36px; border:none; padding:0; border-radius:6px; cursor:pointer;">'+
        '<input type="text" id="newcat-name" placeholder="New site name…" style="flex:1;">'+
        '<button class="btn btn-primary btn-sm" id="add-category">Add site</button>'+
      '</div>'+
    '</div>'+
    (selCat ? (
    '<div class="card"><h2 style="font-size:15px;">Procedures in “'+esc(selCat.name)+'”</h2>'+
      '<div style="display:flex; flex-direction:column; gap:6px; margin-bottom:10px;">'+procRows+'</div>'+
      '<div style="display:flex; gap:8px;">'+
        '<input type="text" id="newproc-input" placeholder="Add a procedure…" style="flex:1;">'+
        '<button class="btn btn-sm btn-primary" data-add-proc="'+esc(selCat.key)+'">Add</button>'+
      '</div>'+
    '</div>') : '')+
    simpleSections;
  }

  function toHexColor(c){
    if(!c) return "#0f6b72";
    if(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(c)) return c;
    var probe = document.createElement("span");
    probe.style.color = c; probe.style.display = "none";
    document.body.appendChild(probe);
    var rgb = getComputedStyle(probe).color;
    document.body.removeChild(probe);
    var m = rgb.match(/\d+/g);
    if(!m) return "#0f6b72";
    return "#"+m.slice(0,3).map(function(n){ return (+n).toString(16).padStart(2,"0"); }).join("");
  }

  /* ============================================================
     RENDER: DEVELOPER - UNITS & ROLES
  ============================================================ */
  function renderDeveloperRoles(){
    if(state.loading) return '<div class="empty-state">Loading…</div>';
    var units = state.config.units || [];
    var groups = {}, order = [];
    units.forEach(function(u){ if(!groups[u.group]){ groups[u.group]=[]; order.push(u.group); } groups[u.group].push(u); });
    var unitSections = order.map(function(g){
      return '<div style="margin-bottom:14px;"><div class="muted" style="font-size:11px; text-transform:uppercase; letter-spacing:.04em; margin-bottom:6px;">'+esc(g||"Units")+'</div>'+
        groups[g].slice().sort(function(a,b){ return String(a.fullName).localeCompare(String(b.fullName), undefined, {sensitivity:"base"}); }).map(function(u){
          return '<div class="proc-opt" style="display:flex; align-items:center; justify-content:space-between; gap:10px; cursor:default;"><span><b class="short-form">'+esc(u.shortForm)+'</b> — '+esc(u.fullName)+'</span><button class="btn btn-sm btn-danger" data-remove-unit="'+esc(u.key)+'">Remove</button></div>';
        }).join("")+
      '</div>';
    }).join("");

    var consultants = state.devUsers.filter(function(u){ return u.role==="consultant"; });
    var roleTypeLabel = { hod:"Head of Department", coordinator:"Course Coordinator", head_of_unit:"Head of Unit" };

    var assignmentRows = state.roleAssignments.slice().sort(function(a,b){ return (b.startAt||"").localeCompare(a.startAt||""); }).map(function(a){
      var active = isAssignmentActive(a);
      var statusChip = active ? '<span class="chip chip-green">Active</span>' : (Date.now() < new Date(a.startAt).getTime() ? '<span class="chip chip-amber">Upcoming</span>' : '<span class="chip chip-grey">Expired</span>');
      return '<tr><td>'+esc(a.consultantDisplayName||a.consultantUsername)+'</td><td>'+esc(roleTypeLabel[a.role]||a.role)+'</td><td>'+(a.unit?unitShortHtml(a.unit):"All units")+'</td><td class="tabular">'+fmtDateTime(a.startAt)+'</td><td class="tabular">'+fmtDateTime(a.endAt)+'</td><td>'+statusChip+'</td><td><button class="btn btn-sm btn-danger" data-remove-assignment="'+a.id+'">End now</button></td></tr>';
    }).join("");

    return ''+
    '<div class="card"><h2>Units</h2>'+
      '<p class="muted" style="margin-bottom:12px; font-size:12.5px;">The master list of units residents rotate through and consultants belong to. Full name shows at entry time; short form (bold) shows in tables and exports.</p>'+
      unitSections+
      '<div class="row3" style="margin-top:10px;">'+
        '<div class="field"><label for="newunit-fullname">Full name</label><input type="text" id="newunit-fullname" placeholder="e.g. Oto-laryngology Unit 6"></div>'+
        '<div class="field"><label for="newunit-shortform">Short form</label><input type="text" id="newunit-shortform" placeholder="e.g. ENT 6"></div>'+
        '<div class="field"><label for="newunit-group">Group</label><select id="newunit-group"><option>Oto-laryngology Units</option><option selected>Peripheral Postings</option></select></div>'+
      '</div>'+
      '<button class="btn btn-sm btn-primary" id="add-unit">Add unit</button>'+
    '</div>'+
    '<div class="card"><h2>Appoint HOD / Course Coordinator / Head of Unit</h2>'+
      '<p class="muted" style="margin-bottom:14px;">HOD and Course Coordinator see every resident’s entire progress across every unit while the appointment is active. Head of Unit sees only their assigned unit’s progress. All three are time-limited — access reverts automatically once the end date/time passes, no action needed.</p>'+
      (consultants.length===0 ? '<p class="muted" style="font-size:13px;">No consultant accounts yet — create one in the Users tab first.</p>' : (
      '<div class="field"><label for="ra-consultant">Consultant</label><select id="ra-consultant">'+consultants.map(function(c){ return '<option value="'+esc(c.username)+'">'+esc(c.displayName)+' ('+esc(c.username)+')</option>'; }).join("")+'</select></div>'+
      '<div class="field"><label for="ra-role">Appointment</label><select id="ra-role" onchange="window.__entlog_toggleUnitField(this.value)">'+
        '<option value="coordinator">Course Coordinator (all units)</option>'+
        '<option value="hod">Head of Department (all units)</option>'+
        '<option value="head_of_unit">Head of Unit (one unit)</option>'+
      '</select></div>'+
      '<div class="field" id="ra-unit-wrap" style="display:none;"><label for="ra-unit">Unit</label><select id="ra-unit">'+unitOptions(null)+'</select></div>'+
      '<div class="row2">'+
        '<div class="field"><label for="ra-start">Starts</label><input id="ra-start" type="datetime-local"></div>'+
        '<div class="field"><label for="ra-end">Ends</label><input id="ra-end" type="datetime-local"></div>'+
      '</div>'+
      '<button class="btn btn-primary" id="add-role-assignment">Add appointment</button>'
      ))+
    '</div>'+
    '<div class="card"><h2>Current & past appointments</h2>'+
      (assignmentRows ? '<div class="table-wrap"><table><thead><tr><th>Consultant</th><th>Role</th><th>Unit</th><th>Starts</th><th>Ends</th><th>Status</th><th></th></tr></thead><tbody>'+assignmentRows+'</tbody></table></div>' : '<p class="muted" style="font-size:13px;">No appointments yet.</p>')+
    '</div>';
  }

  /* ============================================================
     RENDER: ABOUT / ROADMAP
  ============================================================ */
  function renderAbout(){
    return ''+
    '<div class="card"><h2>What this is</h2>'+
      '<p class="muted">A shared ENT logbook — a Dashboard homepage, five entry types (Surgical Procedure, Other Procedure, Interesting Case, Academic Participation, Seminar / Presentation), date-based unit postings, and role-based views (Resident / Consultant / Developer) — running on its own server and database, independent of any third-party platform.</p>'+
    '</div>'+
    '<div class="card"><h2 style="font-size:15px;">Still de-identified — on purpose</h2>'+
      '<p class="muted">Every entry is logged by Hospital Number only, never a patient name. Passwords are hashed on the server (never sent or stored as a reversible form), sessions are httpOnly cookies that can be revoked instantly by a Developer admin, and login attempts are rate-limited. That said: hosting a real department’s hospital numbers still deserves an explicit conversation with your institution’s data-governance or information-security office before this goes past a small pilot with dummy data — technical security and institutional sign-off are two different checkboxes.</p>'+
    '</div>'+
    '<div class="card"><h2 style="font-size:15px;">Units, postings & who can see what</h2>'+
      '<p class="muted">A resident logs their own posting history under <b>My Postings</b> — unit, start date, and (once known) end date. Every entry automatically picks up whichever posting was active on that entry’s date, permanently, so editing postings later never rewrites old history. Consultants have three access levels, set by the Developer under <b>Units & Roles</b>: a plain Consultant sees only their own unit; a Head of Unit sees one assigned unit in full; a Course Coordinator or HOD sees every unit. All three time-boxed appointments revert automatically when they lapse.</p>'+
    '</div>'+
    '<div class="card"><h2 style="font-size:15px;">Developer access</h2>'+
      '<p class="muted">Developers sign in separately (“Developer sign-in”, in fine print at the bottom of the login page) and can: edit every dropdown under <b>Manage Lists</b>; manage the units master list and Head of Unit / Coordinator / HOD appointments under <b>Units & Roles</b>; create ready-made accounts directly under <b>Users</b>, alongside open self-signup; and resolve <b>Password Requests</b> by setting a new password by hand. None of this includes editing this page’s own HTML/CSS/JS — a live in-browser code editor was deliberately left out, since one bad save there would break the tool for everyone with no built-in rollback.</p>'+
    '</div>'+
    '<div class="card roadmap"><h2>Known limitations, on purpose</h2><ul>'+
      '<li><b>De-identified only.</b> No patient-name field anywhere — log by Hospital Number. Please don’t work around that.</li>'+
      '<li><b>Consultants currently see progress only.</b> Verification / sign-off on individual entries is a planned next step.</li>'+
      '<li><b>“Procedure performed” is filtered by the Site you pick.</b> If a case genuinely spans sites, add the extra procedure by free text — it will show up correctly in every count either way.</li>'+
      '<li><b>Password resets are manual.</b> A request just joins the Developer’s queue; there’s no email sending configured, so a resident should also mention it in person if it’s urgent.</li>'+
      '<li><b>Appointment status is computed at render time</b> — correct whenever the page is open, but nobody is proactively notified when one starts or lapses.</li>'+
      '<li><b>No automatic off-site backups yet.</b> The database is one file on the server’s disk — whoever hosts this should schedule regular backups (see the deployment README).</li>'+
      '<li><b>Icons are hand-drawn, not photographs.</b> This page can’t fetch outside images at runtime, so the ear/nose/throat/etc. icons are original line-art rather than sourced photos or plates.</li>'+
      '<li><b>“Seminar / Presentation” is separate from “Academic Participation.”</b> Use Academic Participation for CME/journal club/etc. you attended; use Seminar / Presentation for talks, case presentations or lectures you yourself delivered.</li>'+
    '</ul></div>';
  }

  /* ============================================================
     ROOT RENDER
  ============================================================ */
  function render(){
    var app = el("app");
    if(!app) return;
    if(!state.capReady){
      app.innerHTML = '<div class="center-shell"><div class="auth-card" style="text-align:center;"><div class="auth-eyebrow">Loading</div><h1 style="font-size:20px;">Opening the logbook…</h1></div></div>';
      return;
    }
    if(!state.user){
      var mode = state.authMode;
      app.innerHTML = mode==="signup" ? renderSignup() : (mode==="dev-login" ? renderDevLogin() : (mode==="forgot" ? renderForgot() : (mode==="signup-pending" ? renderSignupPending() : renderLogin())));
      wireAuthEvents();
      return;
    }
    var inner = "";
    if(state.view==="dashboard"){
      inner = isTraineeRole(state.user.role) ? renderDashboardResident() : (state.user.role==="consultant" ? renderDashboardConsultant() : renderDashboardDeveloper());
    }
    else if(state.view==="resident-log") inner = renderResidentLog();
    else if(state.view==="resident-entries") inner = renderResidentEntries();
    else if(state.view==="resident-progress") inner = renderResidentProgress();
    else if(state.view==="resident-postings") inner = renderResidentPostings();
    else if(state.view==="consultant-roster") inner = renderConsultantRoster();
    else if(state.view==="consultant-detail") inner = renderConsultantDetail();
    else if(state.view==="developer-users") inner = renderDeveloperUsers();
    else if(state.view==="developer-password-requests") inner = renderDeveloperPasswordRequests();
    else if(state.view==="developer-lists") inner = renderDeveloperLists();
    else if(state.view==="developer-roles") inner = renderDeveloperRoles();
    else if(state.view==="developer-data") inner = renderDeveloperData();
    else if(state.view==="signup-approvals") inner = renderSignupApprovals();
    else if(state.view==="manage-users") inner = renderManageUsers();
    else if(state.view==="account") inner = renderMyAccount();
    else if(state.view==="about") inner = renderAbout();
    app.innerHTML = renderShell(inner) + (state.viewingEntryId ? renderEntryDetailModal() : "") + (state.viewingHistoryEntryId!=null ? renderEntryHistoryModal() : "");
    wireShellEvents();
  }

  /* ============================================================
     EVENT WIRING
  ============================================================ */
  window.__entlog_setSite = function(val){ wizSetSite(val); };
  // Dispatch table for searchSingleField's row clicks. Most ids (su-unit,
  // nu-unit, posting-unit, and any other plain hidden-field target) have no
  // reactive behaviour beyond "remember the value" -- the hidden input
  // already got that from the inline onclick before this runs, so those
  // just refresh the widget's own visible label/checkmark. The two ids that
  // DO drive other UI (which consultant is picked; which site a procedure
  // block uses, which resets that block's procedure choices) route to the
  // same functions the rest of the wizard already uses for that.
  window.__entlog_ssPick = function(id, value){
    var wrap = document.querySelector('[data-ss-wrap="'+id+'"]');
    var row = wrap ? wrap.querySelector('[data-ss-value="'+value.replace(/"/g,'\\"')+'"]') : null;
    var label = row ? row.getAttribute("data-ss-label") : value;
    if(id==="f-consultantChoice"){ window.__entlog_toggleConsultant(value); ssRefreshVisual(id, value, label); return; }
    ssRefreshVisual(id, value, label);
  };
  // A procedure block's Site select stayed a plain native <select> (only 6
  // sites -- too short to need search), same as before this feature, just
  // routed at a block index now instead of the single flat field.
  window.__entlog_setBlockSite = function(idx, val){ wizSetBlockSite(+idx, val); };
  window.__entlog_wizDateChanged = function(val){
    syncWizFieldsFromDom();
    state.wiz.fields.date = val;
    render();
    loadWizPeopleList();
  };
  window.__entlog_toggleConsultant = function(val){
    if(state.wiz) state.wiz.fields.consultantChoice = val;
    var wrap = el("consultant-other-wrap");
    if(wrap) wrap.style.display = (val==="__other__") ? "" : "none";
  };
  window.__entlog_toggleAcademicOther = function(val){
    if(state.wiz) state.wiz.fields.academicType = val;
    var wrap = el("academic-other-wrap");
    if(wrap) wrap.style.display = (val==="Other") ? "" : "none";
  };
  window.__entlog_toggleSeminarOther = function(val){
    if(state.wiz) state.wiz.fields.seminarType = val;
    var wrap = el("seminar-other-wrap");
    if(wrap) wrap.style.display = (val==="Other") ? "" : "none";
  };
  window.__entlog_toggleUnitField = function(val){
    var wrap = el("ra-unit-wrap");
    if(wrap) wrap.style.display = (val==="head_of_unit") ? "" : "none";
  };

  function wireAuthEvents(){
    var goSignup = el("go-signup"); if(goSignup) goSignup.onclick = function(){ state.authMode="signup"; state.authError=""; render(); };
    var goLogin = el("go-login"); if(goLogin) goLogin.onclick = function(){ state.authMode="login"; state.authError=""; render(); };
    var btnLogin = el("btn-login"); if(btnLogin) btnLogin.onclick = function(){
      doLogin(el("login-username").value, el("login-password").value);
    };
    var pwField = el("login-password"); if(pwField) pwField.addEventListener("keydown", function(ev){ if(ev.key==="Enter") el("btn-login").click(); });

    var goDevLogin = el("go-devlogin"); if(goDevLogin) goDevLogin.onclick = function(){ state.authMode="dev-login"; state.authError=""; render(); };
    var goLoginFromDev = el("go-login-from-dev"); if(goLoginFromDev) goLoginFromDev.onclick = function(){ state.authMode="login"; state.authError=""; render(); };
    var btnDevLogin = el("btn-devlogin"); if(btnDevLogin) btnDevLogin.onclick = function(){
      doLogin(el("dev-username").value, el("dev-password").value, "developer");
    };
    var devPwField = el("dev-password"); if(devPwField) devPwField.addEventListener("keydown", function(ev){ if(ev.key==="Enter") el("btn-devlogin").click(); });

    var goForgot = el("go-forgot"); if(goForgot) goForgot.onclick = function(){ state.authMode="forgot"; state.authError=""; render(); };
    var goLoginFromForgot = el("go-login-from-forgot"); if(goLoginFromForgot) goLoginFromForgot.onclick = function(){ state.authMode="login"; state.authError=""; render(); };
    var btnForgot = el("btn-forgot"); if(btnForgot) btnForgot.onclick = function(){
      submitForgotPassword(el("forgot-username").value, el("forgot-note").value);
    };

    document.querySelectorAll('input[name="signup-role"]').forEach(function(r){
      r.onchange = function(){ state.signupRole = r.value; render(); };
    });
    var btnSignup = el("btn-signup"); if(btnSignup) btnSignup.onclick = function(){
      doSignup({
        username: el("su-username").value, password: el("su-password").value, confirm: el("su-confirm").value,
        displayName: el("su-displayName").value, role: state.signupRole,
        pgYear: (el("su-pgYear")||{}).value, designation: (el("su-designation")||{}).value, unit: (el("su-unit")||{}).value
      });
    };

    var goLoginFromPending = el("go-login-from-pending"); if(goLoginFromPending) goLoginFromPending.onclick = function(){
      state.authMode="login"; state.authError=""; render();
    };
  }

  function wireShellEvents(){
    document.querySelectorAll("[data-nav]").forEach(function(b){
      b.onclick = function(){
        var target = b.getAttribute("data-nav");
        state.mobileNavOpen = false; // picking a destination closes the mobile drawer
        if(target && target.indexOf("__new-")===0){
          state.view = "resident-log";
          render();
          startWizard(target.replace("__new-",""));
          return;
        }
        state.view = target;
        state.wiz = null;
        render();
        loadForView();
      };
    });
    var navToggle = el("btn-nav-toggle");
    if(navToggle) navToggle.onclick = function(){ state.mobileNavOpen = !state.mobileNavOpen; render(); };
    var logout = el("btn-logout"); if(logout) logout.onclick = doLogout;

    // entry-detail modal (opened from the Case Report "Yes" link, or the
    // View button, in My Entries)
    document.querySelectorAll("[data-view-entry]").forEach(function(b){
      b.onclick = function(){ state.viewingEntryId = b.getAttribute("data-view-entry"); render(); };
    });
    var entryDetailClose = el("entry-detail-close"); if(entryDetailClose) entryDetailClose.onclick = function(){ state.viewingEntryId = null; render(); };
    var entryDetailOverlay = el("entry-detail-overlay"); if(entryDetailOverlay) entryDetailOverlay.onclick = function(ev){ if(ev.target===entryDetailOverlay){ state.viewingEntryId = null; render(); } };
    document.querySelectorAll("[data-edit-entry]").forEach(function(b){
      b.onclick = function(){ editEntry(b.getAttribute("data-edit-entry")); };
    });

    // edit-history modal
    document.querySelectorAll("[data-view-history]").forEach(function(b){
      b.onclick = function(){ openEntryHistory(b.getAttribute("data-view-history")); };
    });
    var entryHistoryClose = el("entry-history-close"); if(entryHistoryClose) entryHistoryClose.onclick = function(){ state.viewingHistoryEntryId = null; render(); };
    var entryHistoryOverlay = el("entry-history-overlay"); if(entryHistoryOverlay) entryHistoryOverlay.onclick = function(ev){ if(ev.target===entryHistoryOverlay){ state.viewingHistoryEntryId = null; render(); } };

    // entry wizard
    document.querySelectorAll("[data-start]").forEach(function(b){
      b.onclick = function(){ startWizard(b.getAttribute("data-start")); };
    });
    var wizBack = el("wiz-back"); if(wizBack) wizBack.onclick = cancelWizard;
    var wizSubmit = el("wiz-submit"); if(wizSubmit) wizSubmit.onclick = function(){
      var t = state.wiz.entryType;
      if(t==="surgical") submitSurgical();
      else if(t==="other") submitOther();
      else if(t==="case") submitCase();
      else if(t==="academic") submitAcademic();
      else if(t==="seminar") submitSeminar();
    };
    var addBlockBtn = el("wiz-add-block"); if(addBlockBtn) addBlockBtn.onclick = wizAddBlock;
    document.querySelectorAll("[data-remove-block]").forEach(function(b){
      b.onclick = function(){ wizRemoveBlock(+b.getAttribute("data-remove-block")); };
    });
    document.querySelectorAll(".mp-box").forEach(function(b){
      b.onchange = function(){ mpToggle(b.getAttribute("data-mp-field"), b.value, b.checked); };
    });
    document.querySelectorAll("[data-mp-add-btn]").forEach(function(b){
      b.onclick = function(){
        var key = b.getAttribute("data-mp-add-btn");
        var input = document.querySelector('[data-mp-add-input="'+key+'"]');
        mpAddExtra(key, input ? input.value : "");
        if(input) input.value = "";
      };
    });
    document.querySelectorAll("[data-mp-remove-extra]").forEach(function(b){
      b.onclick = function(){ mpRemoveExtra(b.getAttribute("data-mp-remove-extra"), b.getAttribute("data-mp-extra-value")); };
    });
    // Live text filter for a searchable multi-select's option list -- pure
    // DOM show/hide, deliberately never calls render(): this fires on every
    // keystroke, and a full re-render mid-keystroke would rebuild the input
    // out from under itself and drop focus/cursor position.
    document.querySelectorAll("[data-mp-search]").forEach(function(inp){
      inp.oninput = function(){
        var key = inp.getAttribute("data-mp-search");
        var q = inp.value.trim().toLowerCase();
        var list = document.querySelector('[data-mp-list="'+key+'"]');
        if(!list) return;
        var anyVisible = false;
        list.querySelectorAll(".mp-row").forEach(function(row){
          var match = !q || row.getAttribute("data-mp-row-text").indexOf(q)!==-1;
          row.classList.toggle("sp-row-hidden", !match);
          if(match) anyVisible = true;
        });
        var empty = document.querySelector('[data-mp-empty="'+key+'"]');
        if(empty) empty.classList.toggle("sp-row-hidden", anyVisible || !q);
      };
    });
    // Same idea for a searchable single-select's row list.
    document.querySelectorAll("[data-ss-search]").forEach(function(inp){
      inp.oninput = function(){
        var id = inp.getAttribute("data-ss-search");
        var q = inp.value.trim().toLowerCase();
        var list = document.querySelector('[data-ss-list="'+id+'"]');
        if(!list) return;
        list.querySelectorAll("[data-ss-row]").forEach(function(row){
          var match = !q || row.getAttribute("data-ss-text").indexOf(q)!==-1;
          row.classList.toggle("sp-row-hidden", !match);
        });
      };
      // Selecting-all-then-retyping should re-open the full list, and
      // clicking into an already-chosen field shouldn't force retyping the
      // whole label just to see the other options.
      inp.onfocus = function(){ inp.select(); };
      // Safety net for leaving the field without picking a row (Escape, tab
      // away, click elsewhere on the page): restore the visible text to
      // whatever is actually selected, so a typed-but-abandoned search term
      // never gets left showing as if it were the real value.
      inp.onblur = function(){
        var id = inp.getAttribute("data-ss-search");
        var hidden = document.getElementById(id);
        var list = document.querySelector('[data-ss-list="'+id+'"]');
        var row = (hidden && list) ? list.querySelector('[data-ss-value="'+(hidden.value||"").replace(/"/g,'\\"')+'"]') : null;
        inp.value = row ? row.getAttribute("data-ss-label") : "";
        if(list) list.querySelectorAll("[data-ss-row]").forEach(function(r){ r.classList.remove("sp-row-hidden"); });
      };
    });

    // my entries delete
    document.querySelectorAll("[data-del]").forEach(function(b){
      b.onclick = function(){ removeEntry(b.getAttribute("data-del")); };
    });

    // paper write-up status to-do (immediate commit, PG's own linked cases only)
    document.querySelectorAll("[data-paper-status]").forEach(function(sel){
      sel.onchange = function(){ setPaperStatus(sel.getAttribute("data-paper-status"), sel.value); };
    });

    // dashboard reminder banner dismiss (session-only, resets on next login)
    document.querySelectorAll("[data-dismiss-reminder]").forEach(function(b){
      b.onclick = function(){ state.dismissedReminderKey = b.getAttribute("data-dismiss-reminder"); render(); };
    });

    // resident postings
    var addPostingBtn = el("add-posting"); if(addPostingBtn) addPostingBtn.onclick = function(){
      addPosting((el("posting-unit")||{}).value, (el("posting-date")||{}).value, (el("posting-end")||{}).value);
    };
    document.querySelectorAll("[data-remove-posting]").forEach(function(b){
      b.onclick = function(){ removePosting(Number(b.getAttribute("data-remove-posting"))); };
    });

    // my account
    var changePwBtn = el("btn-change-password"); if(changePwBtn) changePwBtn.onclick = function(){
      changeOwnPassword(el("pw-old").value, el("pw-new").value, el("pw-confirm").value);
    };

    // consultant roster
    document.querySelectorAll("[data-view-resident]").forEach(function(b){
      b.onclick = function(){ openResidentDetail(b.getAttribute("data-view-resident")); };
    });
    var backBtn = el("back-to-roster"); if(backBtn) backBtn.onclick = function(){ state.view="consultant-roster"; render(); };

    // developer
    document.querySelectorAll("[data-apply-role]").forEach(function(b){
      b.onclick = function(){
        var u = b.getAttribute("data-apply-role");
        var sel = document.querySelector('[data-role-select="'+u+'"]');
        if(sel) setUserRole(u, sel.value);
      };
    });
    document.querySelectorAll("[data-toggle-active]").forEach(function(b){
      b.onclick = function(){
        var u = b.getAttribute("data-toggle-active");
        var next = b.getAttribute("data-next")==="true";
        setUserActive(u, next);
      };
    });
    document.querySelectorAll("[data-apply-profile]").forEach(function(b){
      b.onclick = function(){
        var u = b.getAttribute("data-apply-profile");
        var field = b.getAttribute("data-profile-field");
        var sel = document.querySelector('[data-profile-select="'+u+'|'+field+'"]');
        if(sel){
          var patch = {}; patch[field] = sel.value;
          updateUserProfile(u, patch);
        }
      };
    });
    document.querySelectorAll("[data-delete-user]").forEach(function(b){
      b.onclick = function(){ deleteUserAccount(b.getAttribute("data-delete-user")); };
    });

    // signup approvals (developer + HOD/coordinator/head-of-unit)
    document.querySelectorAll("[data-approve-signup]").forEach(function(b){
      b.onclick = function(){ approveSignupRequest(b.getAttribute("data-approve-signup")); };
    });
    document.querySelectorAll("[data-reject-signup]").forEach(function(b){
      b.onclick = function(){ rejectSignupRequest(b.getAttribute("data-reject-signup")); };
    });

    var expE = el("export-entries"); if(expE) expE.onclick = exportEntriesCSV;
    var expU = el("export-users"); if(expU) expU.onclick = exportUsersCSV;
    var expMine = el("export-my-entries"); if(expMine) expMine.onclick = exportMyEntriesCSV;

    // developer - create user
    var toggleCreateBtn = el("toggle-create-user"); if(toggleCreateBtn) toggleCreateBtn.onclick = function(){
      state.showCreateUserForm = !state.showCreateUserForm; render();
    };
    document.querySelectorAll('input[name="newuser-role"]').forEach(function(r){
      r.onchange = function(){ state.newUserRole = r.value; render(); };
    });
    var submitCreateUser = el("submit-create-user"); if(submitCreateUser) submitCreateUser.onclick = function(){
      adminCreateUser({
        username: (el("nu-username")||{}).value, password: (el("nu-password")||{}).value,
        displayName: (el("nu-displayName")||{}).value, role: state.newUserRole || "resident",
        pgYear: (el("nu-pgYear")||{}).value, designation: (el("nu-designation")||{}).value, unit: (el("nu-unit")||{}).value
      });
    };

    // developer - password requests
    document.querySelectorAll("[data-resolve-request]").forEach(function(b){
      b.onclick = function(){
        var id = b.getAttribute("data-resolve-request");
        var username = b.getAttribute("data-resolve-username");
        var input = document.querySelector('[data-pw-input="'+id+'"]');
        adminResetPassword(id, username, input ? input.value : "");
      };
    });

    // developer - units & roles
    var addUnitBtn = el("add-unit"); if(addUnitBtn) addUnitBtn.onclick = function(){
      addUnit((el("newunit-fullname")||{}).value, (el("newunit-shortform")||{}).value, (el("newunit-group")||{}).value);
    };
    document.querySelectorAll("[data-remove-unit]").forEach(function(b){
      b.onclick = function(){ removeUnit(b.getAttribute("data-remove-unit")); };
    });
    var addRoleBtn = el("add-role-assignment"); if(addRoleBtn) addRoleBtn.onclick = function(){
      addRoleAssignment(
        (el("ra-consultant")||{}).value, (el("ra-role")||{}).value, (el("ra-unit")||{}).value,
        (el("ra-start")||{}).value, (el("ra-end")||{}).value
      );
    };
    document.querySelectorAll("[data-remove-assignment]").forEach(function(b){
      b.onclick = function(){ removeRoleAssignment(b.getAttribute("data-remove-assignment")); };
    });

    // developer - manage lists
    document.querySelectorAll("[data-cat-select]").forEach(function(b){
      b.onclick = function(){ state.devListDraft.selectedCat = b.getAttribute("data-cat-select"); render(); };
    });
    document.querySelectorAll("[data-cat-remove]").forEach(function(b){
      b.onclick = function(){ removeCategory(b.getAttribute("data-cat-remove")); };
    });
    document.querySelectorAll("[data-cat-name]").forEach(function(inp){
      inp.addEventListener("change", function(){
        var key = inp.getAttribute("data-cat-name");
        var colorInp = document.querySelector('[data-cat-color="'+key+'"]');
        editCategory(key, inp.value, colorInp ? colorInp.value : null);
      });
    });
    document.querySelectorAll("[data-cat-color]").forEach(function(inp){
      inp.addEventListener("change", function(){
        var key = inp.getAttribute("data-cat-color");
        var nameInp = document.querySelector('[data-cat-name="'+key+'"]');
        editCategory(key, nameInp ? nameInp.value : null, inp.value);
      });
    });
    var addCat = el("add-category"); if(addCat) addCat.onclick = function(){
      addCategory(el("newcat-name").value, el("newcat-color").value);
    };
    document.querySelectorAll("[data-add-proc]").forEach(function(b){
      b.onclick = function(){
        var catKey = b.getAttribute("data-add-proc");
        var input = el("newproc-input");
        addProcedure(catKey, input ? input.value : "");
      };
    });
    document.querySelectorAll("[data-proc-remove]").forEach(function(b){
      b.onclick = function(){ removeProcedure(state.devListDraft.selectedCat, b.getAttribute("data-proc-remove")); };
    });
    document.querySelectorAll("[data-simple-add]").forEach(function(b){
      b.onclick = function(){
        var listKey = b.getAttribute("data-simple-add");
        var input = el("newitem-"+listKey);
        addListItem(listKey, input ? input.value : "");
        if(input) input.value = "";
      };
    });
    document.querySelectorAll("[data-simple-remove]").forEach(function(b){
      b.onclick = function(){
        var listKey = b.getAttribute("data-simple-remove");
        var raw = b.getAttribute("data-idx");
        var sortable = !!(simpleListSpec(listKey)||{}).sortable;
        removeListItem(listKey, sortable ? raw : Number(raw));
      };
    });
  }

  boot();
})();
