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
    detailPostings: [],
    devUsers: [],
    devUsersLoaded: false,
    devAllEntries: [],
    unitOrphans: null,
    approvalSummary: null,
    approvalQueue: null,
    approvalPick: {},          // id -> true, for bulk submit / bulk approve
    exportDialog: null,        // { sel, options, preset }
    feedbackDraft: { kind:"suggestion", subject:"", body:"", anonymous:false },
    feedbackBusy: false,
    feedbackMine: null,
    feedbackInbox: null,
    feedbackFilter: "",
    feedbackOpenId: null,
    feedbackNotes: {},         // id -> notes[]
    feedbackOpenCount: 0,
    account: null,
    accountAction: null,        // "deactivate" | "delete" | null
    accountRequests: null,
    accountArchives: null,
    accountReqCount: 0,
    bulkList: null,             // { key, preview }
    entryLock: null,            // { id, rowVersion } while an edit form is open
    submitDialog: null,        // { ids:[], approver:"" }
    decideDialog: null,        // { id, action }

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
    mobileNavOpen: false,
    // Per-entries-list UI state (search text, sort column/direction, which
    // rows are expanded) keyed by a caller-chosen id -- "my-entries" for the
    // resident/fellow/senior resident's own list, "detail:<username>" for a
    // consultant's per-trainee drill-down. Session/render-only, never
    // persisted -- see entriesUI() below.
    entriesUI: {},
    // Which row's "⋮" action menu is currently open, as "<uiKey>:<entryId>"
    // -- at most one open at a time, across every entries list on screen.
    openEntryMenu: null
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

  // Single-ink anatomical line icons. Drawn on a 24x24 grid because that is
  // the scale they are actually rendered at (16px in .bar-label, 18px in
  // .nav-toggle, 21px in .cat-card, 22px in .dash-card, 26px in .stat-tile) --
  // the previous 40x40 set carried detail that fell below one device pixel
  // once scaled down, so fine strokes greyed out and the cross-hatching
  // disappeared entirely. Everything picks up colour from currentColor, so a
  // category icon can be tinted with its own --cat-* token and both themes
  // work with no second set.
  var ICONS = {
    // ---- site categories -------------------------------------------------
    // Pinna: helix sweeping down to the lobule, with the antihelix inside.
    ear: '<path d="M9 21c-2 0-3.2-1.4-3.2-3.1 0-1.8 1-2.4 1-4.1 0-1.9-1.3-2.6-1.3-5C5.5 5.5 8 3 11.5 3S17.5 5.5 17.5 9c0 2.9-2.1 4-3.5 5-1.1.8-1.6 1.5-1.6 2.6"/><path class="hatch" d="M13.4 8.6c-1.5-.7-3.2.3-3.2 2 0 1.3.9 2 .9 3.1"/>',
    // Nose in profile: bridge, tip, columella, alar crease.
    nose: '<path d="M14.2 3c.5 3.6.2 6-1.3 8.7-.8 1.5-.4 2.8 1.2 3.1l1.5.3"/><path d="M9 15.9c1.1 1.4 2.7 2.1 4.5 2.1 2 0 3.7-.9 4.6-2.4"/><path class="hatch" d="M11.2 18.7c.9.4 1.8.6 2.8.6"/>',
    // Larynx and trachea: the laryngeal box above, tracheal rings below.
    // Tried and rejected on legibility: the glottis on laryngoscopy (read
    // as a letter), palate-arch-plus-tonsils (headphones at 16px, a gas
    // mask once the tongue was added) and rails-and-rungs (a ladder).
    throat: '<rect x="7.4" y="3.3" width="9.2" height="6.8" rx="2.6"/><rect x="8.6" y="12" width="6.8" height="2.6" rx="1.3"/><rect x="8.6" y="15.6" width="6.8" height="2.6" rx="1.3"/><rect x="8.6" y="19.2" width="6.8" height="2.6" rx="1.3"/>',
    // Head & neck: the thyroid, two lobes either side of the trachea. The
    // previous icon was a frontal head-and-shoulders bust, near-identical
    // to the "users" icon it sits beside in the sidebar.
    hn: '<path d="M15.4 20.8v-2.7c2.5-1.4 4.2-4.1 4.2-7.2 0-4.5-3.7-8.1-8.2-8.1-3.6 0-6.7 2.3-7.8 5.6L2.5 12c-.2.6.2 1.3.8 1.4l1.7.4v2.2c0 1.1.9 2 2 2h1.5v2.8"/><circle class="hatch" cx="8.6" cy="10.4" r="1.1"/>',
    // Frontal cranium, orbits only -- the old icon carried orbits, nasal
    // aperture, a jaw notch and hatching on a 40-unit grid, all of which
    // collapsed into a smudge once scaled to 16px.
    skull: '<path d="M12 3.6c-4.4 0-7.8 3.4-7.8 7.9 0 2.4 1 4.4 2.6 5.7v2.1c0 .8.6 1.4 1.4 1.4h7.6c.8 0 1.4-.6 1.4-1.4v-2.1c1.6-1.3 2.6-3.3 2.6-5.7 0-4.5-3.4-7.9-7.8-7.9z"/><circle cx="9.1" cy="11.2" r="1.9"/><circle cx="14.9" cy="11.2" r="1.9"/><path class="hatch" d="M12 14.4l-1 2h2z"/>',
    // Fracture: a broken ring with a fault line through it. The old icon was
    // a shield-and-cross, which everywhere else on the web means "security".
    trauma: '<path d="M8.6 4.3a8.4 8.4 0 0 0-1 14.9M15.4 4.3a8.4 8.4 0 0 1 1 14.9"/><path d="M11.4 3.4 13.7 8.7 10.3 11l3.5 3-1.8 6.6"/>',

    // ---- entry types -----------------------------------------------------
    surgical: '<path d="M3.6 20.4 11 13"/><path d="M11 13l4.9-4.9c1.3-1.3 3.1-2 4.7-1.7.3 1.6-.4 3.4-1.7 4.7L14 16z"/>',
    // Ring-handled instrument -- a minor/bedside procedure, distinct from
    // the scalpel that marks a theatre case. Drawn with its handles because
    // the shafts alone read as a tick and collided with "approvals".
    other: '<circle cx="8.9" cy="5.4" r="2.3"/><circle cx="15.1" cy="5.4" r="2.3"/><path d="M10.1 7.4 12 13.2l1.9-5.8"/><path d="M12 13.2v7.4"/><path class="hatch" d="M9.7 10.3h4.6"/>',
    "case": '<path d="M5.6 3.4h6.8l3.6 3.6v3.4"/><path d="M5.6 3.4v17.2h5"/><path class="hatch" d="M8.4 8.6h3M8.4 11.8h5.2"/><circle cx="16" cy="15.4" r="4.1"/><path d="m19 18.4 2.3 2.3"/>',
    academic: '<path d="M12 3.3 21.6 7.5 12 11.7 2.4 7.5z"/><path d="M6.6 9.6v4.6c0 1.9 2.4 3.4 5.4 3.4s5.4-1.5 5.4-3.4V9.6"/><path class="hatch" d="M21.6 7.5v4.6"/>',
    seminar: '<path d="M3.6 4.2h16.8v9.9H3.6z"/><path d="M12 14.1v2.9M8.3 20.6 12 17l3.7 3.6"/><path class="hatch" d="M7.4 8h9.2"/>',

    // ---- interface -------------------------------------------------------
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    close: '<path d="M6.2 6.2 17.8 17.8M17.8 6.2 6.2 17.8"/>',
    users: '<circle cx="9.4" cy="8" r="3.4"/><path d="M3.2 19.8c0-3.4 2.8-6.2 6.2-6.2s6.2 2.8 6.2 6.2"/><circle class="hatch" cx="17.2" cy="9.4" r="2.5"/><path class="hatch" d="M16.4 14c2.5.4 4.4 2.8 4.4 5.8"/>',
    approvals: '<circle cx="12" cy="12" r="8.5"/><path d="m7.9 12.2 3 3 5.3-5.8"/>',
    password: '<rect x="4.6" y="10.4" width="14.8" height="9.8" rx="2"/><path d="M8.1 10.4V7.6a3.9 3.9 0 0 1 7.8 0v2.8"/><circle class="hatch" cx="12" cy="15" r="1.5"/>',
    units: '<path d="M4.2 20.4V8.1L12 3.8l7.8 4.3v12.3"/><path d="M9.3 20.4v-4.9h5.4v4.9"/><path class="hatch" d="M8.2 11.2h2.6M13.2 11.2h2.6"/>',
    lists: '<path d="M8.6 4.6H6.3c-.9 0-1.7.7-1.7 1.7v12.5c0 .9.7 1.7 1.7 1.7h11.4c.9 0 1.7-.7 1.7-1.7V6.3c0-.9-.7-1.7-1.7-1.7h-2.3"/><rect x="8.6" y="2.8" width="6.8" height="3.6" rx="1.3"/><path class="hatch" d="M8.2 11h7.6M8.2 14.4h7.6M8.2 17.8h4.4"/>',
    "export": '<path d="M12 3.6v11.6M7.8 11l4.2 4.2 4.2-4.2"/><path class="hatch" d="M4.6 17.4v1.6c0 .8.6 1.4 1.4 1.4h12c.8 0 1.4-.6 1.4-1.4v-1.6"/>'
  };
  // Watercolour plates. Unlike icon(), these are photographs of paint, so
  // they are NOT tinted -- see .plate / .art in styles.css for why each one
  // sits on its own paper.
  var ART_KEYS = ["ear","nose","throat","hn","skull","trauma","ossicles",
                  "hearingaid","hands","frame","neuron","facial","theatre"];
  function artPlate(key, extraClass){
    if(ART_KEYS.indexOf(key) === -1) return "";
    return '<span class="plate art a-'+key+(extraClass?" "+extraClass:"")+'" aria-hidden="true"></span>';
  }

  // Skeletons rather than the word "Loading…". The page used to empty out
  // and then snap back full; these hold the shape of what is arriving, so
  // nothing jumps when it lands.
  function skeletonTable(rows){
    var r = "";
    for(var i=0;i<(rows||5);i++) r += '<div class="sk-row"><span class="sk"></span><span class="sk"></span><span class="sk"></span><span class="sk"></span></div>';
    return '<div class="sk-table" aria-busy="true" aria-label="Loading">'+r+'</div>';
  }
  function skeletonDash(){
    var t = "";
    for(var i=0;i<4;i++) t += '<div class="sk-tile"><span class="sk"></span><i class="sk"></i></div>';
    return '<div aria-busy="true" aria-label="Loading"><div class="sk-tiles">'+t+'</div>'+skeletonTable(4)+'</div>';
  }

  // The dark palette was fully built but unreachable: nothing ever set
  // data-theme, so a user on a light OS could not get it. "auto" keeps the
  // previous behaviour of following the system.
  function currentTheme(){
    try{ return localStorage.getItem("entlog.theme") || "auto"; }catch(e){ return "auto"; }
  }
  function applyTheme(t){
    var r = document.documentElement;
    if(t === "auto") r.removeAttribute("data-theme"); else r.setAttribute("data-theme", t);
    try{ localStorage.setItem("entlog.theme", t); }catch(e){}
  }
  function cycleTheme(){
    var order = ["auto","light","dark"];
    applyTheme(order[(order.indexOf(currentTheme())+1) % 3]);
    render();
  }
  function themeButton(){
    var t = currentTheme();
    var label = t==="auto" ? "Theme: follows your system" : (t==="light" ? "Theme: light" : "Theme: dark");
    return '<button type="button" class="theme-btn" id="btn-theme" title="'+esc(label)+'" aria-label="'+esc(label)+'">'+
      icon(t==="dark" ? "skull" : (t==="light" ? "approvals" : "units"))+'</button>';
  }

  /* ============================================================
     APPROVAL — display helpers
     Only operative records and case write-ups are signed off. A linked
     case and its parent operation are two independent approvals.
  ============================================================ */
  var APPROVABLE = ["surgical","other","case"];
  function isApprovable(e){ return APPROVABLE.indexOf(normType(e))!==-1 && e.status!=="draft"; }
  var APPROVAL_LABEL = {
    not_submitted:    ["Not sent",        "chip-grey"],
    pending:          ["Awaiting sign-off","chip-amber"],
    changes_requested:["Changes asked",   "chip-red"],
    approved:         ["Approved",        "chip-green"]
  };
  function approvalChip(e){
    if(!isApprovable(e)) return '<span class="muted" style="font-size:11.5px;">—</span>';
    var st = e.approvalState || "not_submitted";
    var d = APPROVAL_LABEL[st] || APPROVAL_LABEL.not_submitted;
    return '<span class="chip '+d[1]+'">'+esc(d[0])+'</span>';
  }
  function isLocked(e){ return isApprovable(e) && e.approvalState==="approved"; }
  function approverOptions(){
    // Only active consultants. The free-text "consultant" on the entry stays
    // the record of who supervised; this is who signs it off, which is not
    // always the same person.
    return (state.consultantsList||[]).filter(function(c){ return c.role==="consultant"; });
  }

  function icon(key, extraClass){
    var body = ICONS[key];
    if(!body) return "";
    return '<svg class="icon icon-hatch'+(extraClass?" "+extraClass:"")+'" viewBox="0 0 24 24" aria-hidden="true">'+body+'</svg>';
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

  /* ============================================================
     RE-ENTRANCY GUARD

     Every action that writes to the server goes through this. Disabling
     the button is not enough on its own: render() replaces the whole DOM,
     so the disabled button is a NEW element, while the clicks still
     arriving in that same frame land on the OLD one, which is detached but
     very much alive and still carrying its handler. Three fast clicks on
     "Send" therefore produced three records.

     A lock held outside the DOM is checked before any work happens, so the
     duplicate clicks return immediately whichever element they hit.
  ============================================================ */
  var __entlogBusy = {};
  function once(key, fn){
    return async function(){
      if(__entlogBusy[key]) return;
      __entlogBusy[key] = true;
      try { return await fn.apply(this, arguments); }
      finally { __entlogBusy[key] = false; }
    };
  }
  function todayISO(){ var d=new Date(); return d.toISOString().slice(0,10); }
  function fmtDate(s){ if(!s) return "—"; try{ var d=new Date(s+"T00:00:00"); return d.toLocaleDateString(undefined,{day:"2-digit",month:"short",year:"numeric"}); }catch(e){ return s; } }
  function fmtDateTime(s){ if(!s) return "—"; try{ var d=new Date(s); return d.toLocaleString(undefined,{day:"2-digit",month:"short",year:"numeric",hour:"2-digit",minute:"2-digit"}); }catch(e){ return s; } }
  function cleanUsername(u){ return String(u||"").trim().toLowerCase().replace(/[^a-z0-9._-]/g,""); }

  // The dismiss deliberately does NOT re-render. Several fields are read off
  // the live DOM rather than kept in state (the wizard's Comments / History /
  // Examination, the entries search, the developer's new-password box), so a
  // render 3.2s after a toast used to wipe whatever had been typed since.
  function toast(msg){
    state.toast = msg; render();
    setTimeout(function(){
      if(state.toast !== msg) return;
      state.toast = "";
      var b = document.querySelector("[data-toast]");
      if(b && b.parentNode) b.parentNode.removeChild(b);
    }, 3200);
  }

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
    if(!res.ok){
      // Carry the status and the server's own explanation through, instead
      // of flattening everything to a bare code. "entry_locked" on its own
      // is not something to show a person; the `detail` beside it is.
      var err = new Error((data && (data.detail || data.error)) || ("Request failed ("+res.status+")"));
      err.status = res.status;
      err.code = data && data.error;
      err.data = data;
      throw err;
    }
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
  async function dUpdateEntry(id, data){
    // Attach the version this edit was composed against, whenever we are
    // the ones holding the record open. The server refuses the save if the
    // row has moved since, which is what stops two people silently
    // discarding each other's work. Every save path goes through here, so
    // attaching it here covers all of them.
    var payload = data;
    if(state.entryLock && String(state.entryLock.id) === String(id)
       && data && typeof data === "object" && !("rowVersion" in data)){
      payload = Object.assign({}, data, { rowVersion: state.entryLock.rowVersion });
    }
    var entry = (await api("PATCH","/entries/"+id, payload)).entry;
    // Keep our copy of the version current, so a second save in the same
    // sitting is not rejected against the version we ourselves replaced.
    if(state.entryLock && String(state.entryLock.id) === String(id) && entry && entry.rowVersion){
      state.entryLock.rowVersion = entry.rowVersion;
    }
    return entry;
  }
  async function dDeleteEntry(id){ await api("DELETE","/entries/"+id); }
  async function dListEntriesByAuthor(username){
    var path = username===state.user.username ? "/entries/mine" : "/entries/by-author/"+encodeURIComponent(username);
    return (await api("GET", path)).entries;
  }
  // Same endpoint, but the posting blocks the caller is allowed to see --
  // their own unit's for a Head of Unit, all of them for HOD/Coordinator.
  async function dGetAuthorDetail(username){
    return await api("GET","/entries/by-author/"+encodeURIComponent(username));
  }
  async function dListAllEntries(){ return (await api("GET","/entries/all")).entries; }
  async function dGetReminders(){ return (await api("GET","/reminders")).reminders; }
  async function dGetEntryHistory(id){ return (await api("GET","/entries/"+id+"/history")).edits; }
  async function dGetConfig(){ return (await api("GET","/config")).config; }
  async function dGetUnitOrphans(){ return await api("GET","/units/orphans"); }

  /* ---------------- approvals ---------------- */
  async function aSummary(){ return await api("GET","/approvals/summary"); }
  async function aQueue(){ return await api("GET","/approvals/queue"); }
  async function aSubmit(id, approver, comment){ return await api("POST","/entries/"+id+"/submit",{approverUsername:approver, comment:comment}); }
  async function aBulkSubmit(ids, approver){ return await api("POST","/entries/bulk-submit",{ids:ids, approverUsername:approver}); }
  async function aWithdraw(id){ return await api("POST","/entries/"+id+"/withdraw",{}); }
  async function aApprove(id, comment){ return await api("POST","/entries/"+id+"/approve",{comment:comment}); }
  async function aBulkApprove(ids){ return await api("POST","/entries/bulk-approve",{ids:ids}); }
  async function aRequestChanges(id, comment){ return await api("POST","/entries/"+id+"/request-changes",{comment:comment}); }
  async function aRelease(id){ return await api("POST","/entries/"+id+"/release",{}); }
  async function aRequestUnlock(id, comment){ return await api("POST","/entries/"+id+"/request-unlock",{comment:comment}); }
  async function aHistory(id){ return (await api("GET","/entries/"+id+"/approvals")).approvals; }

  /* ---------------- export builder ---------------- */
  async function xOptions(){ return await api("GET","/entries/export/options"); }

  /* ---------------- feedback ---------------- */
  async function fbCreate(body){ return await api("POST","/feedback", body); }
  async function fbMine(){ return (await api("GET","/feedback/mine")).feedback; }
  async function fbInbox(status){ return await api("GET","/feedback"+(status?"?status="+encodeURIComponent(status):"")); }
  async function fbDetail(id){ return (await api("GET","/feedback/"+id)).feedback; }
  async function fbSetStatus(id, status){ return await api("PATCH","/feedback/"+id, {status:status}); }
  async function fbAddNote(id, note){ return (await api("POST","/feedback/"+id+"/notes", {note:note})).notes; }
  async function fbSummary(){ return await api("GET","/feedback/summary"); }

  /* ---------------- account lifecycle ---------------- */
  async function acctOverview(){ return await api("GET","/account/overview"); }
  async function acctDeactivate(reason, note){ return await api("POST","/account/deactivate",{reason:reason, note:note}); }
  async function acctRequestDeletion(reason, username){ return await api("POST","/account/request-deletion",{reason:reason, username:username}); }
  async function acctCancelDeletion(username){ return await api("POST","/account/cancel-deletion",{username:username}); }
  async function acctRequests(){ return await api("GET","/account/requests"); }
  async function acctDecide(id, decision, note){ return await api("POST","/account/requests/"+id+"/decide",{decision:decision, note:note}); }
  async function acctRestore(username, password){ return await api("POST","/account/restore/"+encodeURIComponent(username),{password:password}); }
  async function acctArchives(){ return (await api("GET","/account/archives")).archives; }

  /* ---------------- edit locks ---------------- */
  async function lockEntry(id){ return await api("POST","/entries/"+id+"/lock",{}); }
  async function unlockEntry(id){ try{ return await api("POST","/entries/"+id+"/unlock",{}); }catch(e){ return null; } }

  /* ---------------- bulk list add ---------------- */
  async function bulkAddList(key, text, preview){
    return await api("POST","/config/bulk-add",{list:key, text:text, preview:!!preview});
  }
  async function dUpdateConfig(patch){ return (await api("PATCH","/config", patch)).config; }
  async function dRestoreProcedureDefaults(){ return await api("POST","/config/restore-procedure-defaults",{}); }
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

  async function refreshAccountBadge(){
    var caps = state.capabilities || {};
    if(!(caps.isHod || caps.isCoordinator || caps.isDeveloper)){ state.accountReqCount = 0; return; }
    try{ state.accountReqCount = ((await acctRequests()).pending || []).length; }
    catch(e){ state.accountReqCount = 0; }
  }
  async function refreshFeedbackBadge(){
    if(!canReadFeedback()){ state.feedbackOpenCount = 0; return; }
    try{ state.feedbackOpenCount = (await fbSummary()).open || 0; }catch(e){ state.feedbackOpenCount = 0; }
  }
  async function refreshApprovalSummary(){
    try{ state.approvalSummary = await aSummary(); }catch(e){ state.approvalSummary = null; }
  }
  async function loadForView(){
    if(!state.user) return;
    var v = state.view, role = state.user.role, caps = state.capabilities || {};
    if(v==="dashboard"){
      state.loading = true; render();
      if(isTraineeRole(role)){ await loadMyEntries(); await loadReminders(); await refreshApprovalSummary(); }
      else if(role==="consultant"){
        await loadRoster();
        await refreshApprovalSummary();
        await refreshFeedbackBadge();
        await refreshAccountBadge();
        if(caps.canApprove){ await loadSignupRequests(); }
      }
      else if(role==="developer"){ await refreshFeedbackBadge(); await refreshAccountBadge(); }
      else { await loadDevUsers(); await loadDevEntries(); await loadPasswordRequests(); await loadSignupRequests(); }
      state.loading=false; render(); return;
    }
    if(v==="resident-log"){ await loadConsultants(); render(); return; }
    if(v==="resident-entries" || v==="resident-progress"){ await loadMyEntries(); render(); return; }
    if(v==="consultant-roster"){ await loadRoster(); render(); return; }
    if(v==="developer-users"){ await loadDevUsers(); render(); return; }
    if(v==="developer-roles"){ state.loading=!state.roleAssignmentsLoaded; render(); await loadDevUsers(); await loadRoleAssignments(); state.loading=false; render(); return; }
    if(v==="account"){
      state.loading=true; state.accountAction=null; render();
      try{ state.account = await acctOverview(); }catch(e){ state.account = null; }
      state.loading=false; render(); return;
    }
    if(v==="account-requests"){
      state.loading=true; render();
      try{ state.accountRequests = await acctRequests(); }catch(e){ state.accountRequests = null; }
      if((state.capabilities||{}).isDeveloper){
        try{ state.accountArchives = await acctArchives(); }catch(e){ state.accountArchives = null; }
      }
      state.accountReqCount = (state.accountRequests && state.accountRequests.pending || []).length;
      state.loading=false; render(); return;
    }
    if(v==="feedback"){
      state.loading=true; render();
      try{ state.feedbackMine = await fbMine(); }catch(e){ state.feedbackMine = []; }
      if(canReadFeedback()){
        try{ state.feedbackInbox = await fbInbox(state.feedbackFilter); }catch(e){ state.feedbackInbox = {feedback:[],counts:{}}; }
      }
      await refreshFeedbackBadge();
      state.loading=false; render(); return;
    }
    if(v==="approval-queue"){
      state.loading=true; render();
      await loadConsultants();
      try{ state.approvalQueue = await aQueue(); }catch(e){ state.approvalQueue = null; }
      try{ state.approvalSummary = await aSummary(); }catch(e){}
      state.loading=false; render(); return;
    }
    if(v==="developer-data"){
      state.loading=true; render(); await loadDevUsers(); await loadDevEntries();
      // Rows pointing at a unit the department no longer has. Best-effort:
      // a failure here must not stop the page rendering.
      try{ state.unitOrphans = await dGetUnitOrphans(); }catch(e){ state.unitOrphans = null; }
      state.loading=false; render(); return;
    }
    if(v==="developer-password-requests"){ state.loading=!state.passwordResetsLoaded; render(); await loadDevUsers(); await loadPasswordRequests(); state.loading=false; render(); return; }
    if(v==="signup-approvals"){ state.loading=!state.signupRequestsLoaded; render(); await loadSignupRequests(); state.loading=false; render(); return; }
    if(v==="manage-users"){ state.loading=!state.manageUsersLoaded; render(); await loadManageUsers(); state.loading=false; render(); return; }
  }

  async function openResidentDetail(username){
    state.detailUser = null; state.detailEntries=[]; state.detailPostings=[];
    state.view = "consultant-detail";
    render();
    try{
      var found = state.roster.filter(function(r){ return r.user.username===username; })[0];
      if(found){
        state.detailUser = found.user;
        state.detailEntries = found.entries;
        state.detailPostings = found.postings || [];
      } else {
        state.detailUser = await dGetUser(username);
      }
      // Always re-fetch from the endpoint: the roster row carries only the
      // entries the caller may see, which is right, but the postings panel
      // wants the same list the server would scope for this caller, and a
      // trainee opened from outside the roster has neither.
      var d = await dGetAuthorDetail(username);
      state.detailEntries = d.entries;
      state.detailPostings = d.postings || [];
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
    state.wiz = { entryType:type, fields:fields, linkedFromId:(prefill&&prefill.linkedFromId)||null, editingId:null, status:"final", linkedCaseId:null, origSnapshot:null, peopleList:[], peopleUnit:null, fieldErrors:{} };
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
  function cancelWizard(){
    // Hand the record straight back rather than making the next person wait
    // out the lease.
    releaseEntryLock();
    state.wiz=null; render();
  }

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
  /* ------------------------------------------------------------
     EDIT LEASE

     Claimed when the form opens, refreshed while it stays open, released
     on save or cancel, and expiring by itself if neither happens -- a
     browser gives no dependable signal when a tab closes or a laptop
     shuts, so a lease that waited for an explicit release would strand
     records.
  ------------------------------------------------------------ */
  var __lockTimer = null;
  function stopLockHeartbeat(){
    if(__lockTimer){ clearInterval(__lockTimer); __lockTimer = null; }
  }
  async function releaseEntryLock(){
    stopLockHeartbeat();
    var held = state.entryLock;
    state.entryLock = null;
    if(held) await unlockEntry(held.id);
  }
  async function claimEntryLock(id){
    var r = await lockEntry(id);            // throws 423 if someone else holds it
    state.entryLock = { id: id, rowVersion: r.rowVersion };
    stopLockHeartbeat();
    // Refreshed at a third of the lease, so an open form never lapses
    // while somebody is actually in front of it.
    __lockTimer = setInterval(function(){
      if(!state.entryLock){ stopLockHeartbeat(); return; }
      lockEntry(state.entryLock.id).catch(function(){});
    }, Math.max(60, Math.round((r.lockMinutes||10) * 60 / 3)) * 1000);
    return r;
  }

  async function editEntry(id){
    var e = findEntryById(id);
    if(!e) return;
    try{
      await claimEntryLock(id);
    }catch(err){
      if(err && err.status === 423){
        var who = (err.data && err.data.lock) || {};
        toast((who.displayName || "Someone else") + " has this record open" +
              (who.since ? " (since " + who.since.slice(11,16) + ")" : "") +
              " — it will free up on its own if they have left it.");
        return;
      }
      toast(err && err.message || "Could not open that for editing.");
      return;
    }
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
    state.wiz.status = e.status === "draft" ? "draft" : "final";
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
  // Inline per-field validation flagging: a submit function starts by
  // clearing state.wiz.fieldErrors, then failField() records BOTH the toast
  // (existing behavior) and which field to flag on the re-render toast()
  // triggers -- so the user sees a red-bordered field with its own message
  // instead of the whole form silently going blank (the actual bug report:
  // "the entire form resets" was really "syncWizFieldsFromDom() was never
  // called before the toast-triggered render, so unsync'd inputs collapsed
  // back to their last known state.wiz.fields value, which was often
  // empty"). Every submit* function must call syncWizFieldsFromDom() as its
  // very first line, before this, so the values are never actually lost.
  function failField(key, msg){
    if(!state.wiz) return;
    state.wiz.fieldErrors = state.wiz.fieldErrors || {};
    state.wiz.fieldErrors[key] = msg;
    toast(msg);
  }
  function fieldErr(key){
    return (state.wiz && state.wiz.fieldErrors && state.wiz.fieldErrors[key]) || "";
  }
  // Wraps a field (or a whole form-section, for the procedure-blocks group)
  // with a red border + inline message when fieldErr(key) is set. tag lets
  // callers reuse this for a .form-section as well as a plain .field.
  function fieldGroup(key, innerHtml, tag, extraAttrs){
    var msg = fieldErr(key);
    tag = tag || "field";
    return '<div class="'+tag+(msg?' validation-error':'')+'"'+(extraAttrs||"")+'>'+innerHtml+
      (msg?'<div class="validation-error-msg">'+esc(msg)+'</div>':'')+'</div>';
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
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ failField("hospitalNumber","Hospital number is required."); return; }
    var blocks = f.procedureBlocks||[];
    if(!blocks.length || blocks.some(function(b){ return !b.procedures || !b.procedures.length; })){
      failField("procedures", blocks.length>1 ? "Pick at least one procedure for each site." : "Pick at least one procedure performed."); return;
    }
    if(!f.diagnoses.length){ failField("diagnoses","Pick at least one diagnosis."); return; }
    var cons = resolvedConsultant();
    if(!cons.consultant.trim()){ failField("consultant","Supervising consultant is required."); return; }
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
      caseReport: caseReport, status: "final"
    };
    var editingId = state.wiz.editingId;
    try{
      if(editingId){
        var linkedCaseId = state.wiz.linkedCaseId || null;
        var origSnapshot = state.wiz.origSnapshot || null;
        await dUpdateEntry(editingId, data);
        finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
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
      finishEditing(); state.wiz = null;
      toast("Entry logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  async function submitOther(){
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ failField("hospitalNumber","Hospital number is required."); return; }
    var blocks = f.procedureBlocks||[];
    if(!blocks.length || blocks.some(function(b){ return !b.procedures || !b.procedures.length; })){
      failField("procedures", blocks.length>1 ? "Pick at least one procedure for each site." : "Pick at least one procedure performed."); return;
    }
    if(!f.diagnoses.length){ failField("diagnoses","Pick at least one diagnosis."); return; }
    var cons = resolvedConsultant();
    if(!cons.consultant.trim()){ failField("consultant","Supervising consultant is required."); return; }
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
      assistants: (f.assistantsPicked||[]).join(", "), comments: (el("f-comments")||{}).value || "",
      status: "final"
    };
    var otherEditingId = state.wiz.editingId;
    try{
      if(otherEditingId){ await dUpdateEntry(otherEditingId, data); } else { await dAddEntry(data); }
      finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
      toast(otherEditingId ? "Entry updated." : "Entry logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  // Deliberately skips the submit*() functions' field-by-field validation --
  // a draft is a mid-fill save, so whatever's on the form right now (even
  // blank) is written as-is; the backend's create/update handlers relax
  // procedure-block validation the same way when status is "draft". Only
  // ever called for Surgical/Other Procedure (the only two entry types
  // wizDraftButtons() shows a "Save as draft" button for).
  // Called at the end of every successful save, whichever form it came from.
  function finishEditing(){ releaseEntryLock(); }

  async function wizSaveDraft(){
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var type = state.wiz.entryType;
    var f = state.wiz.fields;
    var entryDate = (el("f-date")||{}).value || f.date || todayISO();
    var blocks = (f.procedureBlocks||[]).map(function(b){
      return { site:b.site||"", procedures:(b.procedures||[]).slice(), laterality:b.laterality||"", role:b.role||"" };
    });
    var flatProcedures = [];
    blocks.forEach(function(b){ (b.procedures||[]).forEach(function(p){ flatProcedures.push(p); }); });
    var cons = resolvedConsultant();
    var data = {
      authorUsername: state.user.username, entryType: type, unit: unitForDate(state.user.postings, entryDate),
      procedureBlocks: blocks, procedures: flatProcedures,
      setting: (el("f-setting")||{}).value || f.setting || "", date: entryDate,
      hospitalNumber: (el("f-hospitalNumber")||{}).value || "", age: (el("f-age")||{}).value || "",
      sex: (el("f-sex")||{}).value || f.sex || "",
      diagnoses: f.diagnoses||[], diagnosesSecondary: f.diagnosesSecondary||[], comorbidities: f.comorbidities||[],
      consultant: cons.consultant.trim(), consultantUsername: cons.consultantUsername,
      assistants: (f.assistantsPicked||[]).join(", "), comments: (el("f-comments")||{}).value || "",
      status: "draft"
    };
    if(type==="surgical") data.caseReport = (el("f-caseReport")||{}).value || f.caseReport || "No";
    if(type==="other") data.otherSettingType = (el("f-otherSettingType")||{}).value || f.otherSettingType || "";
    var editingId = state.wiz.editingId;
    try{
      if(editingId){ await dUpdateEntry(editingId, data); } else { await dAddEntry(data); }
      finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
      toast("Draft saved — you can continue it later from My Entries.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this draft. Please try again."); }
  }

  async function submitCase(){
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var f = state.wiz.fields;
    var hospitalNumber = (el("f-hospitalNumber")||{}).value || "";
    if(!hospitalNumber.trim()){ failField("hospitalNumber","Hospital number is required."); return; }
    if(!f.diagnoses.length){ failField("diagnoses","Pick at least one diagnosis."); return; }
    var history = (el("f-history")||{}).value || "";
    if(!history.trim()){ failField("history","Brief history is required."); return; }
    var examination = (el("f-examination")||{}).value || "";
    if(!examination.trim()){ failField("examination","Examination findings are required."); return; }
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
      finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
      toast(caseEditingId ? "Case updated." : "Case logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this case. Please try again."); }
  }

  async function submitSeminar(){
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var typeVal = (el("f-seminarType")||{}).value;
    var typeOther = (el("f-seminarTypeOther")||{}).value || "";
    if(typeVal==="Other" && !typeOther.trim()){ failField("seminarTypeOther","Describe the activity type."); return; }
    var topic = (el("f-topic")||{}).value || "";
    if(!topic.trim()){ failField("topic","Give the seminar/presentation a topic or title."); return; }
    var details = (el("f-details")||{}).value || "";
    if(!details.trim()){ failField("details","Details are required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var data = {
      authorUsername: state.user.username, entryType:"seminar", unit: unitForDate(state.user.postings, entryDate),
      date: entryDate, seminarType: typeVal, seminarTypeOther: typeVal==="Other" ? typeOther.trim() : "",
      topic: topic.trim(), venue: (el("f-venue")||{}).value || "", details: details.trim()
    };
    var seminarEditingId = state.wiz.editingId;
    try{
      if(seminarEditingId){ await dUpdateEntry(seminarEditingId, data); } else { await dAddEntry(data); }
      finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
      toast(seminarEditingId ? "Entry updated." : "Seminar/presentation logged.");
      state.view = "resident-entries";
      render();
      loadForView();
    }catch(e){ toast("Could not save this entry. Please try again."); }
  }

  async function submitAcademic(){
    syncWizFieldsFromDom();
    state.wiz.fieldErrors = {};
    var f = state.wiz.fields;
    var typeVal = (el("f-academicType")||{}).value;
    var typeOther = (el("f-academicTypeOther")||{}).value || "";
    if(typeVal==="Other" && !typeOther.trim()){ failField("academicTypeOther","Describe the activity type."); return; }
    var details = (el("f-details")||{}).value || "";
    if(!details.trim()){ failField("details","Details are required."); return; }
    var entryDate = (el("f-date")||{}).value || todayISO();
    var data = {
      authorUsername: state.user.username, entryType:"academic", unit: unitForDate(state.user.postings, entryDate),
      date: entryDate, academicType: typeVal, academicTypeOther: typeVal==="Other" ? typeOther.trim() : "",
      details: details.trim()
    };
    var academicEditingId = state.wiz.editingId;
    try{
      if(academicEditingId){ await dUpdateEntry(academicEditingId, data); } else { await dAddEntry(data); }
      finishEditing(); state.wiz = null; state.myEntriesLoaded = false;
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
    // Shallow-merged server-side (cfg.update(body) in api.py), so the WHOLE
    // procedures map has to go up -- sending only the changed key deletes
    // every other site's list.
    var allProcs = JSON.parse(JSON.stringify(state.config.procedures || {}));
    allProcs[key] = [];
    var patch = { categories: newCategories, procedures: allProcs };
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
      // null drops just this site's list server-side; without it the removed
      // site's procedures sat in the config forever and came back if anyone
      // ever re-created a site with the same key.
      var drop = {}; drop[key] = null;
      await dUpdateConfig({ categories: newCategories, procedures: drop });
      delete state.config.procedures[key];
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
    var allProcs = JSON.parse(JSON.stringify(state.config.procedures || {}));
    allProcs[catKey] = list;                 // whole map -- see addCategory
    var patch = { procedures: allProcs };
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
    var allProcs = JSON.parse(JSON.stringify(state.config.procedures || {}));
    allProcs[catKey] = list;                 // whole map -- see addCategory
    var patch = { procedures: allProcs };
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
     EXPORT BUILDER

     Rows (which entries) and columns (which fields), both chosen by the
     person exporting. The server applies the same scope it always did
     BEFORE any filter runs, so nothing here can widen what someone reads --
     a filter only ever narrows what they could already see.

     The selection is remembered in this browser, because the useful case
     is exporting the same shape every few months, not once.
  ============================================================ */
  var EXPORT_PRESETS = {
    operative: { label: "Operative log",
      hint: "What a logbook submission usually wants: what was done, where, which side, and at what level of independence.",
      types: ["surgical","other"],
      columns: ["date","type","unit","site","procedures","laterality","role","setting","consultant","approval"] },
    cases: { label: "Case write-ups",
      hint: "Interesting Cases with their history, examination and diagnoses.",
      types: ["case"],
      columns: ["date","unit","hospitalNumber","age","sex","diagnoses","diagnosesSecondary","comorbidities","history","examination","approval","paperStatus"] },
    teaching: { label: "Teaching record",
      hint: "Academic participation and seminars delivered.",
      types: ["academic","seminar"],
      columns: ["date","type","unit","academicType","seminarType","topic","venue","details"] },
    everything: { label: "Everything",
      hint: "Every entry type, every field. The widest file and the least readable one.",
      types: [], columns: [] },
  };
  var EXPORT_TYPE_LABELS = [
    ["surgical","Surgical procedures"], ["other","Other procedures"], ["case","Interesting cases"],
    ["academic","Academic participation"], ["seminar","Seminars / presentations"],
  ];
  // A sentinel, because the value a "no posting on file" entry actually
  // carries is the empty string -- and an empty string in a query parameter
  // is indistinguishable from "this filter was not set", so ticking only
  // that box would have exported everything.
  var UNIT_NONE = "__none__";
  var EXPORT_APPROVAL_LABELS = [
    ["approved","Approved"], ["pending","Awaiting sign-off"],
    ["changes_requested","Changes asked"], ["not_submitted","Not sent"],
  ];

  function defaultExportSel(){
    return { types: [], columns: EXPORT_PRESETS.operative.columns.slice(),
             units: [], approval: [], authors: [], from: "", to: "" };
  }
  function loadExportSel(){
    try{
      var raw = localStorage.getItem("entlog.export");
      if(raw){
        var v = JSON.parse(raw);
        if(v && Array.isArray(v.columns) && v.columns.length) return Object.assign(defaultExportSel(), v);
      }
    }catch(e){}
    return defaultExportSel();
  }
  function saveExportSel(sel){
    try{ localStorage.setItem("entlog.export", JSON.stringify(sel)); }catch(e){}
  }

  // Counted here rather than asked of the server on every checkbox tick:
  // the entries this person can see are already loaded for the screen they
  // are on. It is an estimate of the same rule, so it is labelled "about".
  function exportRowEstimate(sel){
    var pool = [];
    if(isTraineeRole(state.user.role)) pool = (state.myEntries||[]);
    else if(state.roster && state.roster.length) pool = state.roster.reduce(function(a,r){ return a.concat(r.entries||[]); }, []);
    else return null;
    var n = 0;
    pool.forEach(function(e){
      if(e.status==="draft") return;
      var t = normType(e);
      if(sel.types.length && sel.types.indexOf(t)===-1) return;
      if(sel.units.length && sel.units.indexOf(e.unit || UNIT_NONE)===-1) return;
      if(sel.approval.length && APPROVABLE.indexOf(t)!==-1
         && sel.approval.indexOf(e.approvalState||"not_submitted")===-1) return;
      if(sel.authors.length && sel.authors.indexOf(e.authorUsername)===-1) return;
      if(sel.from && (e.date||"") < sel.from) return;
      if(sel.to && (e.date||"") > sel.to) return;
      n++;
    });
    return n;
  }

  function exportChip(group, value, label, sel){
    var on = (sel[group]||[]).indexOf(value)!==-1;
    return '<label class="pick-chip'+(on?" on":"")+'">'+
      '<input type="checkbox" data-exp-group="'+esc(group)+'" value="'+esc(value)+'"'+(on?" checked":"")+'>'+
      esc(label)+'</label>';
  }

  // Which preset, if any, the current selection happens to equal. Computed
  // rather than remembered, so a preset stays highlighted after a reload and
  // stops being highlighted the moment a selection drifts from it -- either
  // way the highlight describes what is actually selected.
  function matchingPreset(sel){
    function same(a,b){ return a.length===b.length && a.slice().sort().join("|")===b.slice().sort().join("|"); }
    var keys = Object.keys(EXPORT_PRESETS);
    for(var i=0;i<keys.length;i++){
      var p = EXPORT_PRESETS[keys[i]];
      if(same(sel.types, p.types) && same(sel.columns, p.columns)) return keys[i];
    }
    return null;
  }

  function renderExportDialog(){
    var d = state.exportDialog; if(!d) return "";
    var sel = d.sel, opt = d.options;
    if(!opt) return '<div class="modal-overlay" data-export-overlay><div class="modal-card" style="max-width:520px;">'+
      '<h2>Export</h2><p class="muted">Loading what you can export…</p></div></div>';
    var est = exportRowEstimate(sel);
    var active = matchingPreset(sel);
    var allCols = opt.columns || [];
    var picked = sel.columns;
    return '<div class="modal-overlay" data-export-overlay><div class="modal-card modal-wide">'+
      '<button class="modal-close" data-export-cancel aria-label="Close">&times;</button>'+
      '<h2>Export to CSV</h2>'+
      '<p class="muted" style="font-size:13px; margin:6px 0 16px;">Choose which entries go in the file and which columns it has. '+
        'Drafts are never exported. Your choices are remembered on this computer.</p>'+

      '<div class="exp-presets">'+Object.keys(EXPORT_PRESETS).map(function(k){
        return '<button type="button" class="btn btn-sm'+(active===k?" btn-primary":"")+'" data-exp-preset="'+k+'">'+esc(EXPORT_PRESETS[k].label)+'</button>';
      }).join("")+'</div>'+
      (active ? '<p class="muted" style="font-size:12.5px; margin:8px 0 16px;">'+esc(EXPORT_PRESETS[active].hint)+'</p>'
              : '<p class="muted" style="font-size:12.5px; margin:8px 0 16px;">A starting point \u2014 adjust anything below.</p>')+

      '<div class="exp-grid">'+
        '<section><h3>Which entries</h3>'+
          '<div class="exp-sub">Entry type <span class="muted">(none ticked = all)</span></div>'+
          '<div class="pick-row">'+EXPORT_TYPE_LABELS.map(function(t){ return exportChip("types",t[0],t[1],sel); }).join("")+'</div>'+
          '<div class="exp-sub">Dates</div>'+
          '<div class="row2">'+
            '<div class="field"><label for="exp-from">From</label><input id="exp-from" type="date" value="'+esc(sel.from||"")+'"></div>'+
            '<div class="field"><label for="exp-to">To</label><input id="exp-to" type="date" value="'+esc(sel.to||"")+'"></div>'+
          '</div>'+
          ((opt.units||[]).length>1 ? '<div class="exp-sub">Unit</div><div class="pick-row">'+
            opt.units.map(function(u){ return exportChip("units",u,unitShort(u),sel); }).join("")+
            (opt.hasUnattributed ? exportChip("units",UNIT_NONE,"No posting on file",sel) : '')+
          '</div>' : '')+
          ((opt.authors||[]).length>1 ? '<div class="exp-sub">Trainee</div><div class="pick-row">'+
            opt.authors.map(function(a){ return exportChip("authors",a.username,a.displayName||a.username,sel); }).join("")+
          '</div>' : '')+
          '<div class="exp-sub">Sign-off state <span class="muted">(operative records and cases only)</span></div>'+
          '<div class="pick-row">'+EXPORT_APPROVAL_LABELS.map(function(a){ return exportChip("approval",a[0],a[1],sel); }).join("")+'</div>'+
        '</section>'+

        '<section><h3>Which columns <span class="muted" style="font-weight:400; font-size:12.5px;">('+picked.length+' of '+allCols.length+')</span></h3>'+
          '<div class="exp-colbar">'+
            '<button type="button" class="btn btn-sm" data-exp-cols="all">All</button>'+
            '<button type="button" class="btn btn-sm" data-exp-cols="none">None</button>'+
          '</div>'+
          '<div class="exp-cols">'+allCols.map(function(c){
            var on = picked.indexOf(c.key)!==-1;
            return '<label class="exp-col'+(on?" on":"")+'"><input type="checkbox" data-exp-col="'+esc(c.key)+'"'+(on?" checked":"")+'>'+esc(c.label)+'</label>';
          }).join("")+'</div>'+
          '<p class="muted" style="font-size:12px; margin-top:10px;">Columns always come out in this order, whichever you tick, so two exports of the same fields line up.</p>'+
        '</section>'+
      '</div>'+

      '<div class="btn-row">'+
        '<span class="muted" style="font-size:12.5px; align-self:center;">'+
          (est==null ? '' : 'About '+est+' row'+(est===1?'':'s')+' · '+picked.length+' column'+(picked.length===1?'':'s'))+'</span>'+
        '<span style="display:flex; gap:10px;">'+
          '<button class="btn" data-export-cancel>Cancel</button>'+
          '<button class="btn btn-primary" data-export-go'+(picked.length?'':' disabled')+'>Download CSV</button>'+
        '</span>'+
      '</div>'+
    '</div></div>';
  }

  function exportURL(sel){
    // Download is disabled while nothing is ticked, so this is never called
    // with an empty list -- and it must not quietly substitute "all", which
    // is what made the None button look broken.
    var q = [];
    var cols = sel.columns;
    function add(k, arr){ if(arr && arr.length) q.push(k+"="+encodeURIComponent(arr.join(","))); }
    add("columns", cols); add("types", sel.types); add("units", sel.units);
    add("approval", sel.approval); add("authors", sel.authors);
    if(sel.from) q.push("from="+encodeURIComponent(sel.from));
    if(sel.to) q.push("to="+encodeURIComponent(sel.to));
    return "/api/entries/export/custom.csv"+(q.length?"?"+q.join("&"):"");
  }

  /* ============================================================
     RENDER: AUTH SCREENS
  ============================================================ */
  // Every auth screen is the same card on the same shell, so the shell is
  // built once here rather than repeated six times. The card sits in the
  // left column, over the dark side of the theatre photograph; below 901px
  // the photograph is not declared at all and this collapses to the single
  // centred card the app had before -- see .auth-split in styles.css.
  function authShell(inner, opts){
    opts = opts || {};
    var style = (opts.maxWidth ? "max-width:"+opts.maxWidth+"px;" : "") +
                (opts.center ? "text-align:center;" : "");
    return '<div class="auth-split">'+
      '<div class="auth-lockup">'+
        '<div class="brand-mark">E</div>'+
        '<div><div class="t">ENT Surgical Logbook</div>'+
        '<div class="s">Department of Otorhinolaryngology</div></div>'+
      '</div>'+
      '<div class="auth-panel"><div class="auth-card"'+(style?' style="'+style+'"':'')+'>'+
        inner+
      '</div></div>'+
      '<div class="auth-foot">De-identified \u00b7 Hospital Number only</div>'+
    '</div>';
  }

  function renderLogin(){
    return authShell(''+
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
      '<div style="text-align:center; margin-top:18px; padding-top:12px; border-top:1px solid var(--line); font-size:11px;" class="muted"><button class="link-btn" id="go-devlogin" style="font-size:11px; color:var(--ink-soft);">Developer sign-in</button></div>'
    );
  }

  function renderForgot(){
    return authShell(''+
      '<div class="auth-eyebrow">Password reset</div>'+
      '<h1>Request a new password</h1>'+
      '<div class="auth-sub">Your Developer admin sets the new password by hand — this just puts your request in their queue.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label for="forgot-username">Username</label><input id="forgot-username" type="text" autocomplete="username"></div>'+
      '<div class="field"><label for="forgot-note">Note for your admin (optional)</label><textarea id="forgot-note" placeholder="Anything that helps them confirm it&#39;s you"></textarea></div>'+
      '<button class="btn btn-primary" style="width:100%" id="btn-forgot" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Sending…":"Send request")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Remembered it? <button class="link-btn" id="go-login-from-forgot">Back to sign in</button></div>'
    );
  }

  function renderDevLogin(){
    return authShell(''+
      '<div class="auth-eyebrow">Developer sign-in</div>'+
      '<h1>Manage the logbook</h1>'+
      '<div class="auth-sub">Separate from resident/consultant sign-in. Only accounts already granted the Developer role can enter here.</div>'+
      (state.authError ? '<div class="error-banner">'+esc(state.authError)+'</div>' : '')+
      '<div class="field"><label for="dev-username">Developer username</label><input id="dev-username" type="text" autocomplete="username"></div>'+
      '<div class="field"><label for="dev-password">Password</label><input id="dev-password" type="password" autocomplete="current-password"></div>'+
      '<button class="btn btn-primary" style="width:100%" id="btn-devlogin" '+(state.authBusy?"disabled":"")+'>'+(state.authBusy?"Signing in…":"Sign in as Developer")+'</button>'+
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Not a developer? <button class="link-btn" id="go-login-from-dev">Back to regular sign-in</button></div>'
    );
  }

  function renderSignup(){
    var role = state.signupRole;
    var isTrainee = isTraineeRole(role);
    return authShell(''+
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
      '<div style="text-align:center; margin-top:16px; font-size:13px;" class="muted">Already have an account? <button class="link-btn" id="go-login">Sign in</button></div>',
      { maxWidth: 460 }
    );
  }

  function renderSignupPending(){
    // Its own shell rather than authShell(): this is the one screen a new
    // registrar sits and looks at, and the border plate wants the whole
    // viewport rather than the sign-in split.
    return '<div class="auth-framed"><span class="frame-art a-frame"></span>'+
      '<div class="auth-card" style="max-width:380px; text-align:center;">'+
      '<div class="auth-eyebrow">Account created</div>'+
      '<h1>Awaiting approval</h1>'+
      '<div class="auth-sub">'+esc(state.signupPendingMessage)+'</div>'+
      '<button class="btn btn-primary" style="width:100%; margin-top:16px;" id="go-login-from-pending">Back to sign in</button>'+
      '</div></div>';
  }

  function renderSignupPendingUnused(){
    return authShell(''+
      '<div class="auth-eyebrow">Account created</div>'+
      '<h1>Awaiting approval</h1>'+
      '<div class="auth-sub">'+esc(state.signupPendingMessage)+'</div>'+
      '<button class="btn btn-primary" style="width:100%; margin-top:16px;" id="go-login-from-pending">Back to sign in</button>',
      { center: true }
    );
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
  function barRow(label, count, max, color, iconKey, useArt){
    var pct = max>0 ? Math.round((count/max)*100) : 0;
    var lead = useArt ? artPlate(iconKey, "bar-plate") : (iconKey?icon(iconKey):'');
    return '<div class="bar-row"><div class="bar-label">'+lead+'<span>'+esc(label)+'</span></div><div class="bar-track"><span class="bar-fill" style="width:'+pct+'%; background:'+(color||"var(--teal)")+';"></span></div><div class="bar-count">'+count+'</div></div>';
  }

  /* ============================================================
     RENDER: SHELL
  ============================================================ */
  function approvalBadgeCount(){
    var q = (state.approvalSummary||{}).queue;
    return q ? (q.pending||0) : 0;
  }
  function pendingPasswordRequestCount(){
    return state.passwordResets.filter(function(r){ return r.status==="pending"; }).length;
  }
  function navItems(){
    var caps = state.capabilities || {};
    if(isTraineeRole(state.user.role)) return [["dashboard","Dashboard"],["resident-log","Log Entry"],["resident-entries","My Entries"],["resident-progress","My Progress"],["resident-postings","My Postings"],["feedback","Feedback"],["account","My Account"],["about","About / Roadmap"]];
    if(state.user.role==="consultant"){
      var items = [["dashboard","Dashboard"],["consultant-roster","Roster"]];
      // "Approvals" already means account sign-ups in this app, so the case
      // sign-off queue gets its own name rather than a second Approvals.
      items.push(["approval-queue","Case Sign-off"]);
      if(caps.canApprove) items.push(["signup-approvals","Approvals"]);
      if(caps.canManageProfiles) items.push(["manage-users","Manage Users"]);
      items.push(["feedback","Feedback"]);
      if(caps.isHod || caps.isCoordinator) items.push(["account-requests","Account Requests"]);
      items.push(["account","My Account"],["about","About / Roadmap"]);
      return items;
    }
    return [["dashboard","Dashboard"],["developer-users","Users"],["signup-approvals","Approvals"],["developer-password-requests","Password Requests"],["developer-lists","Manage Lists"],["developer-roles","Units & Roles"],["developer-data","Data & Export"],["feedback","Feedback"],["account-requests","Account Requests"],["account","My Account"],["about","About / Roadmap"]];
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
      '<div class="user-chip"><span class="role-badge">'+esc(roleLabelText)+'</span><span>'+esc(state.user.displayName)+'</span>'+themeButton()+'<button class="btn btn-ghost btn-sm" id="btn-logout">Log out</button></div>'+
    '</div>'+
    '<div class="shell-body">'+
      '<nav class="sidenav'+(state.mobileNavOpen?" open":"")+'">'+navItems().map(function(item){
        var badge = "";
        if(item[0]==="developer-password-requests" && pendingCount>0) badge = '<span class="alert-count">'+pendingCount+'</span>';
        if(item[0]==="feedback" && state.feedbackOpenCount>0) badge = '<span class="alert-count">'+state.feedbackOpenCount+'</span>';
        if(item[0]==="account-requests" && state.accountReqCount>0) badge = '<span class="alert-count">'+state.accountReqCount+'</span>';
        if(item[0]==="signup-approvals" && state.signupRequests.length>0) badge = '<span class="alert-count">'+state.signupRequests.length+'</span>';
        if(item[0]==="approval-queue" && approvalBadgeCount()>0) badge = '<span class="alert-count">'+approvalBadgeCount()+'</span>';
        return '<button data-nav="'+item[0]+'" class="'+(state.view===item[0]?"active":"")+'">'+esc(item[1])+badge+'</button>';
      }).join("")+'</nav>'+
      '<main'+((state.view==="resident-entries"||state.view==="consultant-detail")?' class="wide"':'')+'>'+
        (state.toast ? '<div class="success-banner" data-toast>'+esc(state.toast)+'</div>' : '')+
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

  // A draft is a private, incomplete scratch entry -- it hasn't happened
  // yet as far as the logbook's own record of achievement is concerned, so
  // it's excluded from stat tiles and charts (but never from the My Entries
  // list itself, where it stays visible with a "Continue editing" action).
  function finalizedOnly(entries){
    return (entries||[]).filter(function(e){ return e.status !== "draft"; });
  }

  function renderDashboardResident(){
    if(state.loading) return skeletonDash();
    var s = computeStats(finalizedOnly(state.myEntries));
    var todayUnit = unitForDate(state.user.postings, todayISO());
    var recent = finalizedOnly(state.myEntries).slice().sort(function(a,b){ return (b.date||"").localeCompare(a.date||""); }).slice(0,5);
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
      (recent.length===0 ? '<div class="empty-state">'+artPlate("hands","es-plate")+'Nothing logged yet.</div>' :
      '<div class="table-wrap"><table><thead><tr><th>Date</th><th>Type</th><th>Summary</th><th>Unit</th></tr></thead><tbody>'+
        recent.map(function(e){ return '<tr><td class="tabular">'+fmtDate(e.date)+'</td><td>'+entryTypeChip(e)+'</td><td>'+esc(summarizeEntry(e))+'</td><td>'+unitShortHtml(e.unit)+'</td></tr>'; }).join("")+
      '</tbody></table></div>')+
    '</div>';
  }

  function consultantApprovalTiles(){
    var q = (state.approvalSummary||{}).queue; if(!q) return "";
    return '<div class="stat-grid">'+
      statTile(q.pending||0,"Awaiting your sign-off","approvals")+
      statTile(q.overdue||0,"Past "+((state.approvalSummary||{}).escalationDays||7)+" days","close")+
      statTile(q.oldestDays||0,"Oldest, in days","password")+
    '</div>';
  }
  function renderDashboardConsultant(){
    if(state.loading) return skeletonDash();
    var caps = state.capabilities || {};
    var allEntries = [];
    state.roster.forEach(function(r){ allEntries = allEntries.concat(r.entries); });
    var s = computeStats(allEntries);
    return ''+
    renderScopeBanner()+
    consultantApprovalTiles()+
    ((state.approvalSummary||{}).queue && state.approvalSummary.queue.pending ?
      '<div class="card"><div class="dash-grid">'+
        dashCard("approval-queue","Case Sign-off",
          state.approvalSummary.queue.pending+" record"+(state.approvalSummary.queue.pending===1?"":"s")+" waiting for you.",
          null,"approvals","var(--teal)")+
      '</div></div>' : '')+
    overduePanel()+
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
    if(state.loading) return skeletonDash();
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
      // Only operative types contribute to the procedure chart. A linked
      // Interesting Case is pre-filled with its parent surgical entry's
      // procedures, so counting every type double-counted each one.
      if(t==="surgical" || t==="other"){
        entryProcedures(e).forEach(function(p){ procCounts[p] = (procCounts[p]||0)+1; });
      }
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
  // opts.hideTeaching drops the Academic and Seminar tiles. Used on the
  // consultant's view of a trainee: a unit consultant or Head of Unit is
  // looking at operative work, and the teaching record is the Head of
  // Department's and Course Coordinator's business.
  //
  // This is decluttering, NOT access control. The entries themselves are
  // still listed below the charts and the API still returns them, so
  // anyone determined to count them can. Treat it as tidying the view, not
  // as a rule about who may see what.
  function renderStatsAndCharts(entries, opts){
    opts = opts || {};
    var s = computeStats(entries);
    var maxProc = s.procRows.length ? s.procRows[0].count : 0;
    var maxSite = s.siteRows.length ? s.siteRows[0].count : 0;
    var maxUnit = s.unitRows.length ? s.unitRows[0].count : 0;
    var trend = computeMonthlyTrend(entries);
    var maxTrend = trend.length ? Math.max.apply(null, trend.map(function(r){ return r.total; })) : 0;
    return ''+
    '<div class="stats-block"><h3>Total</h3><div class="stat-grid">'+
      statTile(s.total,"Total")+statTile(s.surgical,"Surgical","surgical")+statTile(s.other,"Other","other")+statTile(s["case"],"Cases","case")+
      (opts.hideTeaching ? "" : statTile(s.academic,"Academic","academic")+statTile(s.seminar,"Seminars","seminar"))+
    '</div></div>'+
    (trend.length ? '<div class="card stats-block"><h3>Time-based (entries per month, all types)</h3>'+
      trend.map(function(r){ return barRow(fmtMonthLabel(r.month), r.total, maxTrend, "var(--violet)"); }).join("")+
    '</div>' : '')+
    (s.siteRows.length ? '<div class="card stats-block"><h3>Area-wise (surgical + other procedures, by site)</h3>'+
      s.siteRows.map(function(r){ return barRow(catInfo(r.key).name, r.count, maxSite, catInfo(r.key).color, r.key, true); }).join("")+
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
      return '<div class="notice-banner"><span>You can see records logged under <b>'+
        scope.units.map(function(k){ return esc(unitShort(k)); }).join(", ")+
        '</b> — that is, what each trainee did during their posting there. '+
        'Their work in other units is not shown to you.</span></div>';
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
          '<div class="cat-card" role="button" tabindex="0" data-start="surgical"><span class="icn" style="color:var(--teal);">'+icon("surgical")+'</span><div><div style="font-weight:600;">Surgical Procedure</div><div class="muted" style="font-size:12.5px;">Any OT-booked operative case.</div></div></div>'+
          '<div class="cat-card" role="button" tabindex="0" data-start="other"><span class="icn" style="color:var(--amber);">'+icon("other")+'</span><div><div style="font-weight:600;">Other Procedure</div><div class="muted" style="font-size:12.5px;">OPD, bedside, ED or treatment-room procedures.</div></div></div>'+
          '<div class="cat-card" role="button" tabindex="0" data-start="case"><span class="icn" style="color:var(--ink-soft);">'+icon("case")+'</span><div><div style="font-weight:600;">Interesting Case</div><div class="muted" style="font-size:12.5px;">Rare presentations, diagnostic dilemmas, teaching cases.</div></div></div>'+
          '<div class="cat-card" role="button" tabindex="0" data-start="academic"><span class="icn" style="color:var(--green);">'+icon("academic")+'</span><div><div style="font-weight:600;">Academic Participation</div><div class="muted" style="font-size:12.5px;">CME, journal club, paper presentation, university activity.</div></div></div>'+
          '<div class="cat-card" role="button" tabindex="0" data-start="seminar"><span class="icn" style="color:var(--violet);">'+icon("seminar")+'</span><div><div style="font-weight:600;">Seminar / Presentation</div><div class="muted" style="font-size:12.5px;">Seminars, lectures or case presentations YOU conducted.</div></div></div>'+
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

  // Shared by the Surgical and Other Procedure forms -- the only two that
  // get the Save-as-draft/Finalize workflow (the other three entry types
  // have few enough required fields that a draft state was judged not
  // worth the complexity). A brand-new entry, or a draft being continued,
  // gets both buttons; editing an already-finalized entry keeps the plain
  // single "Save changes" it always had -- flipping a finalized entry back
  // to draft would silently pull it out of the roster/stats a supervisor
  // may have already looked at.
  function wizDraftButtons(){
    var isDraftEdit = state.wiz.editingId && state.wiz.status === "draft";
    var showDraftBtn = !state.wiz.editingId || isDraftEdit;
    var finalizeLabel = state.wiz.editingId && !isDraftEdit ? "Save changes" : "Finalize entry";
    return '<div class="btn-row">'+
      '<button class="btn" id="wiz-back">Cancel</button>'+
      (showDraftBtn ? '<button class="btn" id="wiz-save-draft">Save as draft</button>' : '')+
      '<button class="btn btn-primary" id="wiz-submit">'+finalizeLabel+'</button>'+
    '</div>';
  }
  function wizDraftBadge(){
    return (state.wiz.editingId && state.wiz.status==="draft")
      ? ' <span class="chip chip-amber" style="vertical-align:middle;">Draft</span>' : '';
  }

  function renderSurgicalForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Surgical Procedure'+wizDraftBadge()+'</h2>'+
      (state.wiz.editingId && state.wiz.status==="draft" ? '<p class="muted" style="margin-top:-8px; margin-bottom:16px; font-size:12.5px;">This is a saved draft — it isn\'t counted in your stats or visible to your consultant until you finalize it.</p>' : '')+
      '<div class="form-section"><div class="form-section-title">Patient &amp; procedure details</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-date">Date of procedure</label><input id="f-date" type="date" value="'+esc(f.date)+'" onchange="window.__entlog_wizDateChanged(this.value)"></div>'+
          '<div class="field"><label for="f-setting">Emergency / Elective</label><select id="f-setting">'+opts_(state.config.settings,f.setting)+'</select></div>'+
        '</div>'+
        '<div class="row2">'+
          fieldGroup("hospitalNumber", '<label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419">')+
          '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
        '</div>'+
        '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Diagnoses &amp; comorbidities</div>'+
        fieldGroup("diagnoses", '<label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses))+
        '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
        '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '</div>'+
      fieldGroup("procedures", '<div class="form-section-title">Sites &amp; procedures</div>'+renderProcedureBlocks(true), "form-section")+
      '<div class="form-section"><div class="form-section-title">Consultant &amp; sign-off</div>'+
        fieldGroup("consultant", consultantField())+
        '<div class="field"><label>Assistants <span class="muted">(optional)</span></label>'+multiPicker("assistantsPicked", wizPeopleDisplayNames(), f.assistantsPicked)+'</div>'+
        '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
        '<div class="field"><label for="f-caseReport">Will you be writing a case report?</label><select id="f-caseReport">'+opts_(["No","Yes"],f.caseReport)+'</select><div class="hint">Yes takes you straight into an Interesting Case entry, pre-filled with this case’s Hospital Number, age/sex, diagnoses, comorbidities and procedures.</div></div>'+
      '</div>'+
      wizDraftButtons()+
    '</div>';
  }

  function renderOtherForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Other Procedure'+wizDraftBadge()+'</h2>'+
      (state.wiz.editingId && state.wiz.status==="draft" ? '<p class="muted" style="margin-top:-8px; margin-bottom:16px; font-size:12.5px;">This is a saved draft — it isn\'t counted in your stats or visible to your consultant until you finalize it.</p>' : '')+
      '<div class="form-section"><div class="form-section-title">Patient &amp; procedure details</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-otherSettingType">Setting</label><select id="f-otherSettingType">'+opts_(state.config.otherProcedureSettings,f.otherSettingType)+'</select></div>'+
          '<div class="field"><label for="f-date">Date of procedure</label><input id="f-date" type="date" value="'+esc(f.date)+'" onchange="window.__entlog_wizDateChanged(this.value)"></div>'+
        '</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-setting">Emergency / Elective</label><select id="f-setting">'+opts_(state.config.settings,f.setting)+'</select></div>'+
          fieldGroup("hospitalNumber", '<label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419">')+
        '</div>'+
        '<div class="row2">'+
          '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
          '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
        '</div>'+
      '</div>'+
      '<div class="form-section"><div class="form-section-title">Diagnoses &amp; comorbidities</div>'+
        fieldGroup("diagnoses", '<label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses))+
        '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
        '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '</div>'+
      fieldGroup("procedures", '<div class="form-section-title">Sites &amp; procedures</div>'+renderProcedureBlocks(false), "form-section")+
      '<div class="form-section"><div class="form-section-title">Consultant &amp; sign-off</div>'+
        fieldGroup("consultant", consultantField())+
        '<div class="field"><label>Assistants <span class="muted">(optional)</span></label>'+multiPicker("assistantsPicked", wizPeopleDisplayNames(), f.assistantsPicked)+'</div>'+
        '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
      '</div>'+
      wizDraftButtons()+
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
        fieldGroup("hospitalNumber", '<label for="f-hospitalNumber">Hospital Number</label><input id="f-hospitalNumber" type="text" value="'+esc(f.hospitalNumber||"")+'" placeholder="e.g. HN-238419">')+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+esc(f.date)+'"></div>'+
      '</div>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-age">Age</label><input id="f-age" type="number" min="0" max="130" value="'+esc(f.age||"")+'" placeholder="e.g. 27"></div>'+
        '<div class="field"><label for="f-sex">Sex</label><select id="f-sex">'+opts_(state.config.sexOptions,f.sex)+'</select></div>'+
      '</div>'+
      fieldGroup("diagnoses", '<label>Primary Diagnosis</label>'+multiPicker("diagnoses", state.config.diagnoses, f.diagnoses))+
      '<div class="field"><label>Secondary Diagnosis <span class="muted">(optional)</span></label>'+multiPicker("diagnosesSecondary", state.config.diagnoses, f.diagnosesSecondary)+'</div>'+
      '<div class="field"><label>Comorbidities</label>'+multiPicker("comorbidities", state.config.comorbidities, f.comorbidities)+'</div>'+
      '<div class="field"><label>Procedure(s) performed <span class="muted">(optional)</span></label>'+multiPicker("procedures", allProcs, f.procedures)+'</div>'+
      fieldGroup("history", '<label for="f-history">Brief History</label><textarea id="f-history">'+esc(f.history||"")+'</textarea>')+
      fieldGroup("examination", '<label for="f-examination">Examination Findings</label><textarea id="f-examination">'+esc(f.examination||"")+'</textarea>')+
      '<div class="field"><label for="f-comments">Comments / Complications <span class="muted">(optional)</span></label><textarea id="f-comments">'+esc(f.comments||"")+'</textarea></div>'+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save case")+'</button></div>'+
    '</div>';
  }

  function renderAcademicForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Academic Participation</h2>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+esc(f.date)+'"></div>'+
        '<div class="field"><label for="f-academicType">Type</label><select id="f-academicType" onchange="window.__entlog_toggleAcademicOther(this.value)">'+
          state.config.academicTypes.map(function(t){ return '<option '+(t===f.academicType?"selected":"")+'>'+esc(t)+'</option>'; }).join("")+
          '<option '+(f.academicType==="Other"?"selected":"")+'>Other</option>'+
        '</select></div>'+
      '</div>'+
      fieldGroup("academicTypeOther", '<label for="f-academicTypeOther">Describe the activity type</label><input id="f-academicTypeOther" type="text" value="'+esc(f.academicTypeOther||"")+'">', "field", ' id="academic-other-wrap" style="'+(f.academicType==="Other"?"":"display:none;")+'"')+
      fieldGroup("details", '<label for="f-details">Details</label><textarea id="f-details" style="min-height:120px;">'+esc(f.details||"")+'</textarea>')+
      '<div class="btn-row"><button class="btn" id="wiz-back">Cancel</button><button class="btn btn-primary" id="wiz-submit">'+(state.wiz.editingId?"Save changes":"Save activity")+'</button></div>'+
    '</div>';
  }

  function renderSeminarForm(){
    var f = state.wiz.fields;
    return ''+
    '<div class="card"><h2>'+(state.wiz.editingId?"Edit ":"")+'Seminar / Presentation</h2>'+
      '<p class="muted" style="margin-bottom:16px;">For seminars, lectures or case presentations <b>you</b> conducted — not ones you attended (log those as Academic Participation).</p>'+
      '<div class="row2">'+
        '<div class="field"><label for="f-date">Date</label><input id="f-date" type="date" value="'+esc(f.date)+'"></div>'+
        '<div class="field"><label for="f-seminarType">Type</label><select id="f-seminarType" onchange="window.__entlog_toggleSeminarOther(this.value)">'+
          state.config.seminarTypes.map(function(t){ return '<option '+(t===f.seminarType?"selected":"")+'>'+esc(t)+'</option>'; }).join("")+
          '<option '+(f.seminarType==="Other"?"selected":"")+'>Other</option>'+
        '</select></div>'+
      '</div>'+
      fieldGroup("seminarTypeOther", '<label for="f-seminarTypeOther">Describe the activity type</label><input id="f-seminarTypeOther" type="text" value="'+esc(f.seminarTypeOther||"")+'">', "field", ' id="seminar-other-wrap" style="'+(f.seminarType==="Other"?"":"display:none;")+'"')+
      fieldGroup("topic", '<label for="f-topic">Topic / Title</label><input id="f-topic" type="text" value="'+esc(f.topic||"")+'" placeholder="e.g. Approach to vertigo in primary care">')+
      '<div class="field"><label for="f-venue">Venue / audience <span class="muted">(optional)</span></label><input id="f-venue" type="text" value="'+esc(f.venue||"")+'" placeholder="e.g. Departmental seminar, Unit 4"></div>'+
      fieldGroup("details", '<label for="f-details">Details</label><textarea id="f-details" style="min-height:120px;">'+esc(f.details||"")+'</textarea>')+
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

  /* ============================================================
     ENTRIES LIST: search, sort, expand-in-place accordion.
     Replaces the old wide, all-columns-always-visible table -- shared by
     the resident/fellow/senior-resident "My Entries" list and a
     consultant's per-trainee drill-down, since both are "a list of entries
     with a concise summary line per row that expands to the full detail on
     click" underneath, just with a different action menu.
  ============================================================ */
  // uiKey namespaces one list's search/sort/open-row state -- "my-entries"
  // for a trainee's own list, "detail:<username>" for a consultant's
  // drill-down -- so switching screens (or viewing a different trainee)
  // never leaks one list's state into another's.
  function entriesUI(uiKey){
    state.entriesUI = state.entriesUI || {};
    if(!state.entriesUI[uiKey]) state.entriesUI[uiKey] = { search:"", sortKey:"date", sortDir:"desc", openIds:[] };
    return state.entriesUI[uiKey];
  }
  // Mirrors syncWizFieldsFromDom()'s job for the wizard: the search box is
  // filtered live via pure DOM show/hide (see wireShellEvents' [data-entries-
  // search] handler) and deliberately never calls render() on keystroke, so
  // whatever's actually typed has to be pulled back into state before any
  // OTHER action on this list (sort, expand/collapse, a menu action) calls
  // render() -- otherwise that render would rebuild the list from a stale,
  // pre-keystroke search value and the typed filter text would appear lost.
  function syncEntriesSearchFromDom(uiKey){
    var inp = document.querySelector('[data-entries-search="'+uiKey+'"]');
    if(inp) entriesUI(uiKey).search = inp.value;
  }
  function entrySearchText(e){
    return [
      entryHospitalNumber(e), entryAgeSex(e), summarizeEntry(e), roleLabel(e.entryType),
      entryDiagnoses(e).join(" "), entrySecondaryDiagnoses(e).join(" "), entryComorbidities(e).join(" "),
      entryRoleSummary(e), e.consultant, e.assistants, e.unit, fmtDate(e.date)
    ].join(" ").toLowerCase();
  }
  var ENTRY_SORT_GETTERS = {
    date: function(e){ return e.date||""; },
    createdAt: function(e){ return e.createdAt||""; },
    type: function(e){ return normType(e); },
    hospitalNumber: function(e){ return (entryHospitalNumber(e)||"").toLowerCase(); },
    diagnosis: function(e){ return (entryDiagnoses(e).join(", ")||"").toLowerCase(); },
    role: function(e){ return (entryRoleSummary(e)||"").toLowerCase(); },
    consultant: function(e){ return (e.consultant||"").toLowerCase(); },
    unit: function(e){ return (e.unit||"").toLowerCase(); },
    status: function(e){ return e.status==="draft" ? 0 : 1; }
  };
  var ENTRY_SORT_FIELDS = [
    { key:"date", label:"Date of procedure" }, { key:"createdAt", label:"Date of entry" },
    { key:"type", label:"Type" }, { key:"hospitalNumber", label:"Hospital number" },
    { key:"diagnosis", label:"Diagnosis" }, { key:"role", label:"Role" },
    { key:"consultant", label:"Consultant" }, { key:"unit", label:"Unit" }
  ];
  function sortEntriesFor(uiKey, entries){
    var ui = entriesUI(uiKey);
    var getter = ENTRY_SORT_GETTERS[ui.sortKey] || ENTRY_SORT_GETTERS.date;
    var sorted = entries.slice().sort(function(a,b){
      var av=getter(a), bv=getter(b);
      if(av<bv) return -1; if(av>bv) return 1; return 0;
    });
    if(ui.sortDir==="desc") sorted.reverse();
    return sorted;
  }
  function setEntriesSortKey(uiKey, key){
    syncEntriesSearchFromDom(uiKey);
    var ui = entriesUI(uiKey);
    if(ui.sortKey===key){ ui.sortDir = ui.sortDir==="asc"?"desc":"asc"; }
    else { ui.sortKey = key; ui.sortDir = (key==="date"||key==="createdAt") ? "desc" : "asc"; }
    render();
  }
  function isMobileViewport(){
    try{ return window.matchMedia && window.matchMedia("(max-width:600px)").matches; }
    catch(err){ return (window.innerWidth||9999)<=600; }
  }
  // Expanding a row calls render() (same as every other click-driven state
  // change in this app), so the search box's live-typed value is captured
  // first, exactly like the sort click above.
  function toggleEntryOpen(uiKey, id){
    syncEntriesSearchFromDom(uiKey);
    state.openEntryMenu = null;
    var ui = entriesUI(uiKey);
    id = String(id);
    var idx = ui.openIds.indexOf(id);
    if(idx!==-1){ ui.openIds.splice(idx,1); render(); return; }
    ui.openIds.push(id);
    // Desktop: no cap, any number of rows can stay expanded at once. Mobile:
    // at most 10 -- the earliest-opened one collapses (FIFO) to make room.
    if(isMobileViewport()){
      while(ui.openIds.length>10) ui.openIds.shift();
    }
    render();
  }
  function toggleEntryMenu(menuKey){
    syncEntriesSearchFromDom();   // the box is DOM-only; any render must sync
    var opening = state.openEntryMenu !== menuKey;
    state.openEntryMenu = opening ? menuKey : null;
    render();
  }

  // opts: { uiKey, entries, caseReportRows, emptyText, sortFields,
  //   showStatusBadge, actions(e) -> menu items html or "" to hide the menu,
  //   detail(e) -> extra html appended after the shared entryDetailRows() }
  function renderEntriesList(opts){
    var uiKey = opts.uiKey;
    var ui = entriesUI(uiKey);
    var all = opts.entries || [];
    var q = (ui.search||"").trim().toLowerCase();
    var filtered = !q ? all : all.filter(function(e){ return entrySearchText(e).indexOf(q)!==-1; });
    var sorted = sortEntriesFor(uiKey, filtered);
    var sortFields = opts.sortFields || ENTRY_SORT_FIELDS;
    var toolbar = ''+
      '<div class="entries-toolbar">'+
        '<input type="text" class="entries-search" data-entries-search="'+esc(uiKey)+'" value="'+esc(ui.search||"")+'" placeholder="Search entries…" aria-label="Search entries">'+
        '<div class="entries-sort">'+
          '<span class="muted" style="font-size:12px;">Sort:</span>'+
          '<select data-entries-sort-key="'+esc(uiKey)+'" aria-label="Sort by">'+
            sortFields.map(function(f){ return '<option value="'+f.key+'"'+(ui.sortKey===f.key?' selected':'')+'>'+esc(f.label)+'</option>'; }).join("")+
          '</select>'+
          '<button type="button" class="btn btn-sm" data-entries-sort-dir="'+esc(uiKey)+'" title="Reverse sort order">'+(ui.sortDir==="asc"?"↑ Asc":"↓ Desc")+'</button>'+
        '</div>'+
      '</div>';
    if(all.length===0) return toolbar+'<div class="empty-state">'+artPlate("hands","es-plate")+esc(opts.emptyText||"Nothing logged yet.")+
      (opts.uiKey==="mine" ? '<div class="es-cta"><button class="btn btn-primary" data-nav="resident-log">Log your first entry</button></div>' : '')+'</div>';
    if(sorted.length===0) return toolbar+'<div class="empty-state">No entries match “'+esc(ui.search)+'”.</div>';
    var rowsHtml = sorted.map(function(e,i){
      var idStr = String(e.id);
      var isOpen = ui.openIds.indexOf(idStr)!==-1;
      var menuKey = uiKey+":"+idStr;
      var menuItems = opts.actions ? opts.actions(e) : "";
      var isDraft = e.status==="draft";
      return ''+
      '<div class="entry-card'+(isOpen?' entry-card-open':'')+'" data-entries-search-text="'+esc(entrySearchText(e))+'">'+
        '<div class="entry-card-summary" role="button" tabindex="0" aria-expanded="'+(isOpen?"true":"false")+'" data-entry-toggle="'+esc(uiKey)+'" data-entry-id="'+esc(idStr)+'">'+
          '<span class="entry-card-num tabular muted">'+(i+1)+'</span>'+
          '<span class="entry-card-date tabular">'+fmtDate(e.date)+'</span>'+
          entryTypeChip(e)+
          '<span class="entry-card-main">'+esc(entryHospitalNumber(e)||summarizeEntry(e)||"—")+'</span>'+
          '<span class="entry-card-sub muted">'+esc(entryDiagnoses(e).join(", ")||summarizeEntry(e)||"")+'</span>'+
          (opts.showStatusBadge && isDraft ? ' <span class="chip chip-amber">Draft</span>' : '')+
          (opts.showApproval && !isDraft ? '<span class="entry-card-approval">'+approvalChip(e)+'</span>' : '')+
          (opts.selectable && isApprovable(e) && (e.approvalState==="not_submitted"||e.approvalState==="changes_requested")
            ? '<label class="row-pick" title="Select for bulk send"><input type="checkbox" data-pick="'+esc(idStr)+'"'+(state.approvalPick[idStr]?" checked":"")+'></label>' : '')+
          '<span class="entry-card-chevron" aria-hidden="true">▼</span>'+
          (menuItems ? (
            '<span class="entry-menu-wrap">'+
              '<button type="button" class="btn btn-sm entry-menu-btn" data-entry-menu-btn="'+esc(menuKey)+'" aria-label="Row actions">⋮</button>'+
              (state.openEntryMenu===menuKey ? '<div class="entry-menu" data-entry-menu="'+esc(menuKey)+'">'+menuItems+'</div>' : '')+
            '</span>'
          ) : '')+
        '</div>'+
        (isOpen ? (
          '<div class="entry-card-detail">'+
            entryDetailRows(e).map(function(r){ return '<div class="detail-row"><div class="k">'+esc(r[0])+'</div><div>'+r[1]+'</div></div>'; }).join("")+
            (opts.detail ? opts.detail(e) : "")+
          '</div>'
        ) : '')+
      '</div>';
    }).join("");
    return toolbar+'<div class="entry-list">'+rowsHtml+'</div>';
  }

  function residentEntryMenuItems(e, rows){
    var items = [];
    var st = e.approvalState || "not_submitted";
    if(isApprovable(e)){
      if(st==="not_submitted" || st==="changes_requested")
        items.push('<button type="button" data-send-approval="'+e.id+'">Send for sign-off</button>');
      if(st==="pending")
        items.push('<button type="button" data-withdraw="'+e.id+'">Withdraw from sign-off</button>');
      if(st==="approved")
        items.push('<button type="button" data-request-unlock="'+e.id+'">Ask to unlock</button>');
      items.push('<button type="button" data-approval-history="'+e.id+'">Sign-off history</button>');
    }
    items.push('<button type="button" data-view-history="'+e.id+'">Edit history</button>');
    // An approved record is locked: the consultant attested to this exact
    // version. Edit and Delete are not offered at all rather than offered
    // and then refused by the server.
    if(!isLocked(e)){
      items.push('<button type="button" data-edit-entry="'+e.id+'">'+(e.status==="draft"?"Continue editing":"Edit")+'</button>');
      items.push('<button type="button" class="entry-menu-danger" data-del="'+e.id+'">Delete</button>');
    }
    return items.join("");
  }

  /* ============================================================
     APPROVAL — dialogs
  ============================================================ */
  function renderSubmitDialog(){
    var d = state.submitDialog; if(!d) return "";
    var opts = approverOptions();
    var many = d.ids.length > 1;
    return '<div class="modal-overlay" data-submit-overlay><div class="modal-card" style="max-width:440px;">'+
      '<button class="modal-close" data-submit-cancel aria-label="Close">&times;</button>'+
      '<h2>Send '+(many ? d.ids.length+' records' : 'this record')+' for sign-off</h2>'+
      '<p class="muted" style="font-size:13px; margin:6px 0 16px;">'+
        'The consultant you pick will be asked to sign '+(many?'these off':'this off')+'. '+
        'Once signed, the record is locked and you will need them to release it before you can edit it again.</p>'+
      (opts.length ?
        '<div class="field"><label for="submit-approver">Send to</label>'+
          '<select id="submit-approver">'+
            '<option value="">Choose a consultant…</option>'+
            opts.map(function(c){
              return '<option value="'+esc(c.username)+'"'+(c.username===d.approver?" selected":"")+'>'+esc(c.displayName)+'</option>';
            }).join("")+
          '</select></div>'+
        '<div class="field"><label for="submit-note">Note (optional)</label>'+
          '<textarea id="submit-note" placeholder="Anything the consultant should know"></textarea></div>'
        : '<div class="notice-banner"><span>No active consultant accounts to send to yet. Ask your Developer admin to add one.</span></div>')+
      '<div class="btn-row"><button class="btn" data-submit-cancel>Cancel</button>'+
        '<button class="btn btn-primary" data-submit-go '+(opts.length?"":"disabled")+'>Send</button></div>'+
    '</div></div>';
  }

  function renderDecideDialog(){
    var d = state.decideDialog; if(!d) return "";
    var asking = d.action === "changes";
    return '<div class="modal-overlay" data-decide-overlay><div class="modal-card" style="max-width:440px;">'+
      '<button class="modal-close" data-decide-cancel aria-label="Close">&times;</button>'+
      '<h2>'+(asking ? "Ask for changes" : "Sign this off")+'</h2>'+
      '<p class="muted" style="font-size:13px; margin:6px 0 14px;">'+
        (asking ? 'The trainee sees your note at the top of the record. Say what needs changing — "changes requested" with no reason usually comes back unchanged.'
                : 'You are confirming this record as an accurate account of the case. It will be locked to further editing until you release it.')+'</p>'+
      '<div class="field"><label for="decide-note">'+(asking?"What needs changing":"Note (optional)")+'</label>'+
        '<textarea id="decide-note" placeholder="'+(asking?"e.g. Laterality is recorded as right; this was a left ear.":"")+'"></textarea></div>'+
      '<div class="btn-row"><button class="btn" data-decide-cancel>Cancel</button>'+
        '<button class="btn '+(asking?"":"btn-primary")+'" data-decide-go>'+(asking?"Send back":"Sign off")+'</button></div>'+
    '</div></div>';
  }

  /* ============================================================
     APPROVAL — consultant queue
  ============================================================ */
  function queueRow(e, delegated){
    var over = e.overdue;
    return '<div class="q-row'+(over?' q-overdue':'')+'">'+
      '<label class="row-pick"><input type="checkbox" data-qpick="'+e.id+'"'+(state.approvalPick[String(e.id)]?" checked":"")+'></label>'+
      '<div class="q-main">'+
        '<div class="q-top">'+entryTypeChip(e)+
          '<b>'+esc(entryHospitalNumber(e)||summarizeEntry(e)||"—")+'</b>'+
          '<span class="muted">'+esc(summarizeEntry(e)||"")+'</span></div>'+
        '<div class="q-meta muted">'+esc(e.authorDisplayName||userDisplay(e.authorUsername))+' &middot; '+fmtDate(e.date)+
          ' &middot; '+unitShortHtml(e.unit)+
          ' &middot; <span class="'+(over?"q-age-over":"")+'">waiting '+e.waitingDays+'d</span>'+
          (delegated ? ' &middot; <span class="chip chip-violet">for '+esc(e.approverDisplayName||userDisplay(e.onBehalfOf))+'</span>' : '')+
          (e.unlockRequested ? ' &middot; <span class="chip chip-amber">unlock asked</span>' : '')+
        '</div></div>'+
      '<div class="q-act">'+
        '<button class="btn btn-sm" data-open-entry="'+e.id+'">Open</button>'+
        '<button class="btn btn-sm" data-ask-changes="'+e.id+'">Changes</button>'+
        '<button class="btn btn-sm btn-primary" data-sign-off="'+e.id+'">Sign off</button>'+
      '</div></div>';
  }

  function renderApprovalQueue(){
    if(state.loading) return skeletonDash();
    var q = state.approvalQueue || { queue:[], delegated:[], escalationDays:7 };
    var picked = Object.keys(state.approvalPick).filter(function(k){ return state.approvalPick[k]; });
    var bar = picked.length ? '<div class="bulk-bar"><span>'+picked.length+' selected</span>'+
      '<button class="btn btn-sm" data-pick-clear>Clear</button>'+
      '<button class="btn btn-sm btn-primary" data-bulk-approve>Sign off '+picked.length+'</button></div>' : '';
    function section(title, rows, delegated, note){
      if(!rows.length) return "";
      return '<div class="card"><div class="section-head"><h2>'+title+' ('+rows.length+')</h2></div>'+
        (note ? '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">'+note+'</p>' : '')+
        '<div class="q-list">'+rows.map(function(e){ return queueRow(e, delegated); }).join("")+'</div></div>';
    }
    if(!q.queue.length && !q.delegated.length){
      return '<div class="card"><div class="empty-state">'+artPlate("ossicles","es-plate")+
        'Nothing waiting for your sign-off.</div></div>';
    }
    return bar+
      section("Waiting for you", q.queue, false, "Oldest first. Anything past "+q.escalationDays+" days is flagged.")+
      section("You can also sign these off", q.delegated, true,
        "Sent to another consultant, but you can act on them as Head of Unit / Coordinator / HOD — useful when they are away. Your name is recorded as acting on their behalf.");
  }

  function approvalCounters(){
    var m = (state.approvalSummary||{}).mine; if(!m) return "";
    return '<div class="stat-grid">'+
      statTile(m.approved||0,"Signed off","approvals")+
      statTile(m.pending||0,"Awaiting sign-off","password")+
      statTile(m.changes_requested||0,"Changes asked","close")+
      statTile(m.not_submitted||0,"Not sent","export")+
    '</div>';
  }

  function overduePanel(){
    var sum = state.approvalSummary || {};
    var list = sum.unitOverdue || [];
    if(!list.length) return "";
    return '<div class="card"><div class="section-head"><h2>Waiting more than '+(sum.escalationDays||7)+' days</h2>'+
      '<span class="chip chip-red">'+(sum.unitOverdueTotal||list.length)+'</span></div>'+
      '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">Records sitting unsigned in units you oversee. '+
        'In-app notice only reaches a consultant when they log in, so this is what stops one person being away from stalling a trainee\u2019s logbook.</p>'+
      '<div class="table-wrap"><table><thead><tr><th>Trainee</th><th>Unit</th><th>Sent to</th><th>Date</th><th>Waiting</th></tr></thead><tbody>'+
      list.map(function(o){
        return '<tr><td>'+esc(o.author)+'</td><td>'+unitShortHtml(o.unit)+'</td>'+
          '<td>'+esc(o.approver||"\u2014")+'</td><td class="tabular">'+fmtDate(o.date)+'</td>'+
          '<td class="tabular"><b>'+o.waitingDays+'d</b></td></tr>';
      }).join("")+'</tbody></table></div></div>';
  }

  function userDisplay(username){
    if(!username) return "\u2014";
    var all = (state.consultantsList||[]).concat(state.devUsers||[]).concat(state.roster||[]);
    var m = all.filter(function(u){ return u.username===username; })[0];
    return m ? (m.displayName||username) : username;
  }

  function renderResidentEntries(){
    if(state.loading) return skeletonDash();
    var rows = state.myEntries;
    var picked = Object.keys(state.approvalPick).filter(function(k){ return state.approvalPick[k]; });
    var bulkBar = picked.length ? '<div class="bulk-bar"><span>'+picked.length+' selected</span>'+
      '<button class="btn btn-sm" data-pick-clear>Clear</button>'+
      '<button class="btn btn-sm btn-primary" data-bulk-send>Send '+picked.length+' for sign-off</button></div>' : '';
    return ''+
    approvalCounters()+
    bulkBar+
    '<div class="card"><div class="section-head"><h2>My Entries ('+rows.length+')</h2><button class="btn btn-sm" id="open-export">Export\u2026</button></div>'+
    renderEntriesList({
      uiKey: "my-entries",
      entries: rows,
      showStatusBadge: true,
      showApproval: true,
      selectable: true,
      emptyText: "Nothing logged yet.",
      actions: function(e){ return residentEntryMenuItems(e, rows); },
      detail: function(e){
        var extra = '';
        if(isApprovable(e)){
          extra += '<div class="detail-row"><div class="k">Sign-off</div><div>'+approvalChip(e)+
            (e.approverUsername ? ' <span class="muted" style="font-size:12px;">'+
              (e.approvalState==="approved"?"by ":"with ")+esc(userDisplay(e.approverUsername))+'</span>' : '')+
            (isLocked(e) ? ' <span class="muted" style="font-size:12px;">\u00b7 locked</span>' : '')+
            '</div></div>';
        }
        if(e.paperStatus!=null) extra += '<div class="detail-row"><div class="k">Write-up</div><div>'+paperStatusCell(e)+'</div></div>';
        extra += '<div class="detail-row"><div class="k">Case report</div><div>'+caseReportCell(e, rows)+'</div></div>';
        return extra;
      }
    })+
    '</div>';
  }

  // Every field worth showing about one entry, as [label, htmlValue] pairs --
  // shared by the "View" modal (cross-list navigation, e.g. a case-report
  // link that points at an entry outside the current list) and each entries
  // list's own inline expand-in-place panel, so the two never drift apart.
  function entryDetailRows(e){
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
    return rows;
  }

  function renderEntryDetailModal(){
    var e = findEntryById(state.viewingEntryId);
    if(!e) return "";
    var t = normType(e);
    var rows = entryDetailRows(e);
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
    if(state.loading) return skeletonDash();
    return renderStatsAndCharts(finalizedOnly(state.myEntries));
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

  /* ============================================================
     MY ACCOUNT
  ============================================================ */
  var ROLE_ASSIGNMENT_LABEL = {
    hod: "Head of Department", coordinator: "Course Coordinator", head_of_unit: "Head of Unit",
  };
  var ACCOUNT_STATE_CHIP = {
    active:      null,
    deactivated: ["Deactivated", "chip-amber"],
    closing:     ["Closing",     "chip-red"],
    deleted:     ["Account closed", "chip-grey"],
    unknown:     ["No longer on the system", "chip-grey"],
  };
  // Shown beside a name wherever it appears. A closed account's name stays
  // on the records it is part of -- they are somebody else's evidence -- so
  // it is flagged rather than removed.
  function accountStateChip(state_){
    var d = ACCOUNT_STATE_CHIP[state_ || "active"];
    return d ? ' <span class="chip '+d[1]+'" style="font-size:10.5px;">'+esc(d[0])+'</span>' : "";
  }

  function kv(k, v){
    return '<div class="acct-kv"><div class="k">'+esc(k)+'</div><div class="v">'+(v||'<span class="muted">—</span>')+'</div></div>';
  }

  function renderMyAccount(){
    var a = state.account;
    if(!a) return skeletonDash();
    var p = a.profile;
    var isTrainee = isTraineeRole(p.role);

    var identity = '<div class="card"><div class="section-head"><h2>'+esc(p.displayName)+'</h2>'+
        '<span class="chip chip-teal">'+esc(roleLabel(p.role))+'</span></div>'+
      '<div class="acct-grid">'+
        kv("Username", '<span class="tabular">'+esc(p.username)+'</span>')+
        kv("Role", esc(roleLabel(p.role)))+
        kv(isTrainee ? "Batch" : "Designation", esc((isTrainee ? p.pgYear : p.designation) || ""))+
        kv(isTrainee ? "Current posting" : "Unit", p.unit ? unitShortHtml(p.unit)+' <span class="muted">'+esc(unitFull(p.unit))+'</span>' : "")+
        kv("Account opened", fmtDate((p.createdAt||"").slice(0,10)))+
        kv("Last signed in", p.lastSeenAt ? fmtDateTime(p.lastSeenAt) : "")+
      '</div></div>';

    // Appointments, with how long each has actually run.
    var appts = "";
    if(!isTrainee){
      var rows = (a.assignments||[]).map(function(x){
        var served = x.startAt ? daysBetween(x.startAt, x.endAt && x.endAt < todayISO() ? x.endAt : todayISO()) : null;
        return '<tr><td>'+esc(ROLE_ASSIGNMENT_LABEL[x.role]||x.role)+'</td>'+
          '<td>'+(x.unit ? unitShortHtml(x.unit) : '<span class="muted">All units</span>')+'</td>'+
          '<td class="tabular">'+fmtDate(x.startAt)+'</td>'+
          '<td class="tabular">'+(x.endAt ? fmtDate(x.endAt) : '<span class="muted">open</span>')+'</td>'+
          '<td class="tabular">'+(served!=null && served>0 ? humanSpan(served) : "—")+'</td>'+
          '<td><span class="chip '+(x.active?"chip-green":"chip-grey")+'">'+(x.active?"In force":"Lapsed")+'</span></td></tr>';
      }).join("");
      appts = '<div class="card"><h2 style="font-size:15px;">Appointments</h2>'+
        (rows ? '<div class="table-wrap"><table><thead><tr><th>Role</th><th>Unit</th><th>From</th><th>To</th><th>Served</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>'
              : '<p class="muted" style="font-size:13px;">No Head of Unit, Course Coordinator or Head of Department appointment on file.</p>')+
      '</div>';
    }

    // Postings, for a trainee.
    var postings = "";
    if(isTrainee){
      var b = postingBlocks(a.postings||[]);
      var prow = b.all.slice().reverse().map(function(x){
        var st = x.startDate>b.today ? ["Upcoming","chip-teal"]
          : (!x.endDate || x.endDate>=b.today) ? ["Current","chip-green"] : ["Completed","chip-grey"];
        var end = (!x.endDate || x.endDate>b.today) ? b.today : x.endDate;
        return '<tr><td>'+unitShortHtml(x.unit)+'</td><td class="tabular">'+fmtDate(x.startDate)+'</td>'+
          '<td class="tabular">'+(x.endDate?fmtDate(x.endDate):'<span class="muted">open</span>')+'</td>'+
          '<td class="tabular">'+(x.startDate>b.today ? "—" : humanSpan(daysBetween(x.startDate,end)))+'</td>'+
          '<td><span class="chip '+st[1]+'">'+st[0]+'</span></td></tr>';
      }).join("");
      postings = '<div class="card"><div class="section-head"><h2 style="font-size:15px;">My postings</h2>'+
          '<span class="muted" style="font-size:12.5px;">'+humanSpan(b.servedDays)+' served</span></div>'+
        (prow ? '<div class="table-wrap"><table><thead><tr><th>Unit</th><th>From</th><th>To</th><th>Served</th><th></th></tr></thead><tbody>'+prow+'</tbody></table></div>'
              : '<p class="muted" style="font-size:13px;">None yet — add them under My Postings.</p>')+
      '</div>';
    }

    // Who else is in this unit.
    var m = a.members || {consultants:[], trainees:[]};
    function memberList(list, empty){
      if(!list.length) return '<p class="muted" style="font-size:13px;">'+empty+'</p>';
      return '<div class="member-list">'+list.map(function(x){
        return '<div class="member'+(x.username===p.username?" me":"")+'">'+
          '<span class="member-name">'+esc(x.displayName)+accountStateChip(x.status)+
            (x.username===p.username?' <span class="chip chip-teal" style="font-size:10.5px;">You</span>':'')+'</span>'+
          '<span class="muted">'+esc(x.designation || x.pgYear || roleLabel(x.role))+'</span>'+
        '</div>';
      }).join("")+'</div>';
    }
    var unitCard = '<div class="card"><h2 style="font-size:15px;">'+
        (p.unit ? esc(unitShort(p.unit))+' — who else is here' : 'Your unit')+'</h2>'+
      (p.unit ? '<div class="row2">'+
          '<div><div class="exp-sub">Consultants</div>'+memberList(m.consultants, "None on file for this unit.")+'</div>'+
          '<div><div class="exp-sub">Trainees</div>'+memberList(m.trainees, "Nobody posted here at the moment.")+'</div>'+
        '</div>'
        : '<p class="muted" style="font-size:13px;">'+(isTrainee
            ? 'No posting covers today, so there is no unit to show. Add one under My Postings.'
            : 'No home unit is set on your account. Your Developer admin can set one.')+'</p>')+
    '</div>';

    // Password, condensed to one row.
    var password = '<div class="card"><h2 style="font-size:15px;">Password</h2>'+
      '<div class="row3">'+
        '<div class="field"><label for="pw-old">Current</label><input id="pw-old" type="password" autocomplete="current-password"></div>'+
        '<div class="field"><label for="pw-new">New</label><input id="pw-new" type="password" autocomplete="new-password"></div>'+
        '<div class="field"><label for="pw-confirm">Confirm new</label><input id="pw-confirm" type="password" autocomplete="new-password"></div>'+
      '</div>'+
      '<div class="btn-row"><span class="muted" style="font-size:12.5px; align-self:center;">Locked out instead? Sign out and use “Forgot your password?”.</span>'+
        '<button class="btn btn-primary" id="btn-change-password">Update password</button></div>'+
    '</div>';

    return identity + appts + postings + unitCard + password + renderAccountClosure(a);
  }

  /* ------------------------------------------------------------
     Closing an account: deactivate (reversible by signing in) or
     delete (approved, then a buffer, then a tombstone).
  ------------------------------------------------------------ */
  function renderAccountClosure(a){
    var req = a.request;
    var days = a.deletionBufferDays || 14;

    if(req && req.kind === "delete"){
      var pending = req.status === "pending";
      return '<div class="card danger-card">'+
        '<div class="section-head"><h2 style="font-size:15px;">Account closure</h2>'+
          '<span class="chip '+(pending?"chip-amber":"chip-red")+'">'+
            (pending ? "Awaiting approval" : "Closing in "+(req.daysRemaining==null?days:req.daysRemaining)+" days")+'</span></div>'+
        '<p style="font-size:13.5px;">'+(pending
          ? 'Your request to close this account is with '+esc(req.requestedBy===state.user.username?"the Head of Department":"whoever can approve it")+'. Nothing has changed yet.'
          : 'This account is scheduled to close on <b>'+fmtDate((req.scheduledFor||"").slice(0,10))+'</b>. '+
            'Until then it can still be stopped.')+'</p>'+
        '<p class="muted" style="font-size:12.5px;">Reason given: '+esc(req.reason||"—")+'</p>'+
        '<div class="btn-row"><span></span>'+
          '<button class="btn" id="cancel-deletion">Stop the closure</button></div>'+
      '</div>';
    }

    var reasons = a.deactivationReasons || [];
    var mode = state.accountAction;
    return '<div class="card danger-card">'+
      '<h2 style="font-size:15px;">Taking a break, or leaving</h2>'+
      '<div class="acct-actions">'+
        '<button class="btn'+(mode==="deactivate"?" btn-primary":"")+'" data-acct-action="deactivate">Deactivate my account</button>'+
        '<button class="btn btn-danger'+(mode==="delete"?" btn-primary":"")+'" data-acct-action="delete">Close my account permanently</button>'+
      '</div>'+
      (mode==="deactivate" ?
        '<div class="acct-panel">'+
          '<p style="font-size:13.5px;">Takes effect immediately and signs you out. '+
            '<b>You bring it back simply by signing in again</b> — nobody has to do anything for you. '+
            'Your entries, sign-offs and everything else stay exactly as they are.</p>'+
          '<div class="field"><label for="deact-reason">Reason</label><select id="deact-reason">'+
            reasons.map(function(r){ return '<option>'+esc(r)+'</option>'; }).join("")+'</select></div>'+
          '<div class="field"><label for="deact-note">Anything to add (optional)</label>'+
            '<textarea id="deact-note" rows="2" placeholder="Your unit sees this, so they know when to expect you back."></textarea></div>'+
          '<div class="btn-row"><button class="btn" data-acct-action="">Cancel</button>'+
            '<button class="btn btn-primary" id="do-deactivate">Deactivate and sign out</button></div>'+
        '</div>' : '')+
      (mode==="delete" ?
        '<div class="acct-panel">'+
          '<div class="notice-banner"><span>This is not reversible after '+days+' days. '+
            (isTraineeRole(a.profile.role)
              ? 'Your logbook is the evidence for your certification — the entries themselves are kept and stay visible to your consultants, but <b>you will lose access to them</b>.'
              : 'Your name stays on every operation record and sign-off you are part of, flagged as closed, because those records belong to the trainees who logged them.')+
          '</span></div>'+
          '<p style="font-size:13.5px;">What happens: your request goes to '+
            (isTraineeRole(a.profile.role) ? 'the <b>Head of Department</b>' : 'the <b>Head of Department or a Developer admin</b>')+
            '. If they agree, the account is suspended and a <b>'+days+'-day</b> countdown starts. '+
            'You or they can stop it at any point in those '+days+' days. After that the sign-in is destroyed '+
            'and the profile cleared, while everything you logged stays on the system.</p>'+
          '<div class="field"><label for="del-reason">Why are you closing it?</label>'+
            '<textarea id="del-reason" rows="3" placeholder="This is recorded and shown to whoever decides."></textarea></div>'+
          '<div class="btn-row"><button class="btn" data-acct-action="">Cancel</button>'+
            '<button class="btn btn-danger" id="do-request-deletion">Request closure</button></div>'+
        '</div>' : '')+
    '</div>';
  }

  /* ============================================================
     ACCOUNT REQUESTS  (Head of Department / Developer)
  ============================================================ */
  function renderAccountRequests(){
    if(state.loading) return skeletonDash();
    var d = state.accountRequests;
    if(!d) return '<div class="card"><div class="empty-state">Loading…</div></div>';
    var days = d.bufferDays || 14;

    function reqRow(r, inBuffer){
      var trainee = isTraineeRole((r.roleOfUser||""));
      return '<div class="q-row'+(inBuffer?" q-overdue":"")+'">'+
        '<div class="q-main">'+
          '<div class="q-top"><b>'+esc(r.displayName||r.username)+'</b>'+
            '<span class="chip '+(inBuffer?"chip-red":"chip-amber")+'">'+
              (inBuffer ? (r.daysRemaining==null?days:r.daysRemaining)+" days left" : "Awaiting decision")+'</span></div>'+
          '<div class="fb-body">'+esc(r.reason||"No reason given.")+'</div>'+
          '<div class="q-meta muted">Asked by '+esc(r.requestedByName||r.requestedBy)+
            ' · '+fmtDateTime(r.requestedAt)+
            (inBuffer && r.scheduledFor ? ' · closes '+fmtDate((r.scheduledFor||"").slice(0,10)) : '')+
            (r.decidedBy ? ' · approved by '+esc(r.decidedBy) : '')+'</div>'+
        '</div>'+
        '<div class="q-act">'+
          (inBuffer
            ? '<button class="btn btn-sm" data-acct-cancel="'+esc(r.username)+'">Stop closure</button>'
            : '<button class="btn btn-sm" data-acct-decide="'+r.id+'" data-decision="reject">Refuse</button>'+
              '<button class="btn btn-sm btn-danger" data-acct-decide="'+r.id+'" data-decision="approve">Approve closure</button>')+
        '</div></div>';
    }

    var pending = d.pending || [], buffer = d.inBuffer || [], off = d.deactivated || [];
    return ''+
      '<div class="stat-grid">'+
        statTile(pending.length, "Awaiting your decision", "approvals")+
        statTile(buffer.length, "Closing within "+days+" days", "close")+
        statTile(off.length, "Currently deactivated", "password")+
      '</div>'+
      '<div class="card"><h2>Closure requests</h2>'+
        '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">'+
          'Approving one suspends the account and starts a '+days+'-day countdown. Nothing is destroyed '+
          'until it runs out, and it can be stopped at any point. Entries, sign-offs and names on '+
          'operation records are kept whatever happens.'+
          (d.canDecideTrainees ? '' : ' Trainee accounts can only be decided by the Head of Department.')+'</p>'+
        (pending.length ? '<div class="q-list">'+pending.map(function(r){ return reqRow(r,false); }).join("")+'</div>'
                        : '<p class="muted" style="font-size:13px;">Nothing waiting.</p>')+
      '</div>'+
      (buffer.length ? '<div class="card"><h2 style="font-size:15px;">Closing soon</h2>'+
        '<div class="q-list">'+buffer.map(function(r){ return reqRow(r,true); }).join("")+'</div></div>' : '')+
      '<div class="card"><h2 style="font-size:15px;">Deactivated accounts</h2>'+
        '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">'+
          'Someone who switched their own account off comes back the moment they sign in. '+
          'One an admin switched off stays off until an admin turns it back on.</p>'+
        (off.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Role</th><th>Why</th><th>Since</th><th>Switched off by</th></tr></thead><tbody>'+
          off.map(function(u){
            return '<tr><td>'+esc(u.displayName)+'</td><td>'+esc(roleLabel(u.role))+'</td>'+
              '<td>'+esc(u.reason||"—")+'</td><td class="tabular">'+fmtDate((u.since||"").slice(0,10))+'</td>'+
              '<td>'+(u.lifecycle==="self_deactivated"
                 ? '<span class="chip chip-teal">Themselves</span>'
                 : '<span class="chip chip-amber">An admin</span>')+'</td></tr>';
          }).join("")+'</tbody></table></div>'
          : '<p class="muted" style="font-size:13px;">None.</p>')+
      '</div>'+
      (state.accountArchives ? renderAccountArchives() : '');
  }

  function renderAccountArchives(){
    var rows = state.accountArchives || [];
    return '<div class="card"><h2 style="font-size:15px;">Archived accounts</h2>'+
      '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">'+
        'A full copy of the account and everything it logged, taken the moment closure was approved. '+
        'Developer-only. Downloading one gives you a JSON file you can keep or hand back.</p>'+
      (rows.length ? '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Username</th><th>Archived</th><th>By</th><th></th></tr></thead><tbody>'+
        rows.map(function(r){
          return '<tr><td>'+esc(r.display_name||"—")+'</td><td class="tabular">'+esc(r.username)+'</td>'+
            '<td class="tabular">'+fmtDate((r.archived_at||"").slice(0,10))+'</td><td>'+esc(r.archived_by||"—")+'</td>'+
            '<td><button class="btn btn-sm" data-archive-dl="'+r.id+'">Download</button>'+
              '<button class="btn btn-sm" data-archive-restore="'+esc(r.username)+'">Restore login</button></td></tr>';
        }).join("")+'</tbody></table></div>'
        : '<p class="muted" style="font-size:13px;">None yet.</p>')+
    '</div>';
  }

  /* ============================================================
     RENDER: CONSULTANT
  ============================================================ */
  // Whole-department oversight: Head of Department and Course Coordinator.
  // A plain consultant and a Head of Unit see the operative columns only.
  function seesTeachingColumns(){
    var caps = state.capabilities || {};
    return !!(caps.isHod || caps.isCoordinator || caps.isDeveloper);
  }

  // Days between two ISO dates, inclusive of the start day. Kept to whole
  // days and rendered as weeks/months, because a posting is a rota block --
  // "11 wks in" is the useful figure, "79 days" is not.
  function daysBetween(fromISO, toISO){
    var a = new Date(fromISO+"T00:00:00"), b = new Date(toISO+"T00:00:00");
    if(isNaN(a) || isNaN(b)) return null;
    return Math.floor((b-a)/86400000) + 1;
  }
  function humanSpan(days){
    if(days==null) return "";
    if(days < 14) return days+(days===1?" day":" days");
    if(days < 70) return Math.round(days/7)+" wks";
    var m = days/30.44;
    return (m<10 ? m.toFixed(1) : String(Math.round(m)))+" mo";
  }

  // Sorts and classifies a set of posting blocks against today.
  function postingBlocks(postings){
    var today = todayISO();
    var list = (postings||[]).filter(function(p){ return p.startDate; })
      .slice().sort(function(a,b){ return a.startDate.localeCompare(b.startDate); });
    var live = list.filter(function(p){ return p.startDate<=today && (!p.endDate || p.endDate>=today); });
    var past = list.filter(function(p){ return p.endDate && p.endDate<today; });
    var future = list.filter(function(p){ return p.startDate>today; });
    // Days counted only up to today for a block still running, so "time in
    // this unit" is time actually served, not time scheduled.
    var served = 0;
    list.forEach(function(p){
      if(p.startDate>today) return;
      var end = (!p.endDate || p.endDate>today) ? today : p.endDate;
      var d = daysBetween(p.startDate, end);
      if(d>0) served += d;
    });
    return { all:list, live:live[live.length-1]||null, past:past, future:future, servedDays:served, today:today };
  }

  // Progress through one block: dates, how far in, and a bar.
  function postingProgress(p, today){
    var elapsed = daysBetween(p.startDate, today);
    var total = p.endDate ? daysBetween(p.startDate, p.endDate) : null;
    var pct = (total && total>0) ? Math.min(100, Math.round((elapsed/total)*100)) : null;
    return '<div class="posting-dates tabular">'+fmtDate(p.startDate)+' – '+(p.endDate?fmtDate(p.endDate):'open')+'</div>'+
      '<div class="posting-elapsed">'+humanSpan(elapsed)+' in'+
        (total ? ' <span class="muted">of '+humanSpan(total)+'</span>' : '')+'</div>'+
      (pct!=null ? '<div class="posting-bar" role="img" aria-label="'+pct+'% through this posting"><span style="width:'+pct+'%"></span></div>' : '');
  }

  // HOD / Course Coordinator column: the posting the trainee is on TODAY,
  // wherever that is. Replaces the old "Last entry" column -- their most
  // recent entry is still the first row of their entry list.
  function currentPostingCell(postings){
    var b = postingBlocks(postings);
    if(!b.live){
      // Three different situations, three different people to chase:
      // nothing on file is a data-entry gap, a gap between blocks is a rota
      // gap, and a block that has not started yet is neither.
      if(b.future.length)
        return '<div class="posting-cell"><span class="chip chip-teal">Starts '+fmtDate(b.future[0].startDate)+'</span></div>';
      return '<span class="muted">'+(b.all.length ? "Between postings" : "No postings on file")+'</span>';
    }
    return '<div class="posting-cell">'+postingProgress(b.live, b.today)+'</div>';
  }

  // Head of Unit column: how long this trainee has spent in THIS unit,
  // which is the figure a unit's consultant is actually accountable for.
  // Their current unit is a separate column, because it is often somewhere
  // else entirely and the department still needs to know where they are.
  function unitTimeCell(postings){
    var b = postingBlocks(postings);
    // Count only blocks that have actually started. A trainee who did one
    // rotation and is booked for a second has served 3 months across ONE
    // posting, not two -- counting the booking would overstate the figure
    // this column exists to report.
    var servedBlocks = b.all.filter(function(p){ return p.startDate<=b.today; }).length;
    var totalLine = servedBlocks>1
      ? '<div class="posting-elapsed muted">'+humanSpan(b.servedDays)+' across '+servedBlocks+' postings</div>' : '';
    var returns = b.future.length
      ? '<div class="posting-elapsed"><span class="chip chip-teal">'+
          (servedBlocks ? 'Returns ' : 'Starts ')+fmtDate(b.future[0].startDate)+'</span></div>' : '';

    if(b.live) return '<div class="posting-cell">'+postingProgress(b.live, b.today)+totalLine+returns+'</div>';
    if(b.past.length){
      // Served time leads, because that is the figure a unit is accountable
      // for. A booked return is secondary -- it was reading as the headline
      // for someone who had already been and gone.
      var last = b.past[b.past.length-1];
      return '<div class="posting-cell">'+
        '<div class="posting-dates tabular">'+fmtDate(last.startDate)+' – '+fmtDate(last.endDate)+'</div>'+
        '<div class="posting-elapsed">'+humanSpan(b.servedDays)+
          (servedBlocks>1 ? ' across '+servedBlocks+' postings' : ' served')+'</div>'+
        returns+
      '</div>';
    }
    if(b.future.length) return '<div class="posting-cell">'+returns+'</div>';
    return '<span class="muted">—</span>';
  }

  // The "where are they now" marker, shown to everyone. A Head of Unit gets
  // this one fact about units they do not oversee -- not the trainee's
  // rotation history, which the server withholds.
  function currentUnitCell(row){
    var u = row.currentUnit || unitForDate(row.postings, todayISO());
    if(!u) return '<span class="muted">—</span>';
    return unitShortHtml(u);
  }

  function renderConsultantRoster(){
    if(state.loading) return skeletonTable(5);
    var banner = renderScopeBanner();
    if(state.roster.length===0) return banner+'<div class="card"><div class="empty-state">No trainees’ entries are visible to you right now.</div></div>';
    var teaching = seesTeachingColumns();
    var full = !!(state.consultantScope && state.consultantScope.full);
    var myUnits = (state.consultantScope && state.consultantScope.units) || [];
    var unitName = myUnits.length===1 ? unitShort(myUnits[0]) : "your units";
    return banner+''+
    '<div class="card"><div class="section-head"><h2>Trainee roster</h2><button class="btn btn-sm" id="open-export">Export…</button></div>'+
    (full ? '' : '<p class="muted" style="font-size:12.5px; margin:-6px 0 14px;">'+
      'Everyone who has been, is, or is due to be posted to '+esc(unitName)+'. '+
      'The counts and the case records are for their time in '+esc(unitName)+' only \u2014 not their whole logbook. '+
      '\u201cCurrently in\u201d shows where they are today, which may be elsewhere.</p>')+
    '<div class="table-wrap"><table class="roster-table"><thead><tr>'+
      '<th>Trainee</th><th>Role</th><th>Batch</th><th>Currently in</th>'+
      '<th>Total</th><th>Surgical</th><th>Other</th><th>Cases</th>'+
      (teaching ? '<th>Academic</th><th>Seminars</th>' : '')+
      '<th>'+(full ? 'Current posting' : 'Time in '+esc(unitName))+'</th><th></th>'+
    '</tr></thead><tbody>'+
      state.roster.map(function(r){
        var s = computeStats(r.entries);
        return '<tr>'+
          '<td>'+esc(r.user.displayName)+'</td>'+
          '<td><span class="chip chip-grey">'+esc(roleLabel(r.user.role))+'</span></td>'+
          '<td>'+esc(r.user.pgYear||"—")+'</td>'+
          '<td>'+currentUnitCell(r)+'</td>'+
          '<td class="tabular">'+s.total+'</td><td class="tabular">'+s.surgical+'</td>'+
          '<td class="tabular">'+s.other+'</td><td class="tabular">'+s["case"]+'</td>'+
          (teaching ? '<td class="tabular">'+s.academic+'</td><td class="tabular">'+s.seminar+'</td>' : '')+
          '<td>'+(full ? currentPostingCell(r.postings) : unitTimeCell(r.postings))+'</td>'+
          '<td><button class="btn btn-sm" data-view-resident="'+esc(r.user.username)+'">View</button></td>'+
        '</tr>';
      }).join("")+
    '</tbody></table></div></div>';
  }

  // The posting blocks behind everything on this page. For a Head of Unit
  // these are their own unit's blocks only -- the server does not send the
  // rest -- so the panel doubles as a statement of what the records below
  // it cover.
  function renderPostingBlocks(){
    var list = state.detailPostings || [];
    var full = !!(state.consultantScope && state.consultantScope.full);
    if(!list.length){
      return '<div class="card"><h2 style="font-size:15px;">Postings</h2>'+
        '<p class="muted" style="font-size:13px;">No postings on file'+(full?'':' in your unit')+'.</p></div>';
    }
    var b = postingBlocks(list);
    var rows = b.all.slice().reverse().map(function(p){
      var state_ = p.startDate>b.today ? ["Upcoming","chip-teal"]
        : (!p.endDate || p.endDate>=b.today) ? ["Current","chip-green"] : ["Completed","chip-grey"];
      var end = (!p.endDate || p.endDate>b.today) ? b.today : p.endDate;
      var served = p.startDate>b.today ? null : daysBetween(p.startDate, end);
      return '<tr><td>'+unitShortHtml(p.unit)+'</td>'+
        '<td class="tabular">'+fmtDate(p.startDate)+'</td>'+
        '<td class="tabular">'+(p.endDate?fmtDate(p.endDate):'<span class="muted">open</span>')+'</td>'+
        '<td class="tabular">'+(served!=null?humanSpan(served):'<span class="muted">—</span>')+'</td>'+
        '<td><span class="chip '+state_[1]+'">'+state_[0]+'</span></td></tr>';
    }).join("");
    return '<div class="card"><div class="section-head"><h2 style="font-size:15px;">Postings'+
        (full?'':' in your unit')+'</h2>'+
        '<span class="muted" style="font-size:12.5px;">'+humanSpan(b.servedDays)+' served'+
          (b.all.length>1 ? ' across '+b.all.length+' postings' : '')+'</span></div>'+
      (full ? '' : '<p class="muted" style="font-size:12.5px; margin:-6px 0 12px;">'+
        'The records below cover these postings only.</p>')+
      '<div class="table-wrap"><table><thead><tr><th>Unit</th><th>From</th><th>To</th><th>Served</th><th></th></tr></thead>'+
      '<tbody>'+rows+'</tbody></table></div></div>';
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
    var uiKey = "detail:"+state.detailUser.username;
    return ''+
    renderScopeBanner()+
    '<button class="btn btn-sm" id="back-to-roster" style="margin-bottom:14px;">← Back to roster</button>'+
    '<div class="card"><h2>'+esc(state.detailUser.displayName)+'</h2><p class="muted">'+esc(state.detailUser.pgYear||"")+'</p></div>'+
    renderPostingBlocks()+
    renderStatsAndCharts(entries, { hideTeaching: !seesTeachingColumns() })+
    '<div class="card"><h2>Entries ('+entries.length+')</h2>'+
    renderEntriesList({
      uiKey: uiKey,
      entries: entries,
      emptyText: "No entries visible to you.",
      sortFields: ENTRY_SORT_FIELDS.filter(function(f){ return f.key!=="consultant"; }),
      actions: showHistory ? function(e){ return '<button type="button" data-view-history="'+e.id+'">History</button>'; } : null,
      detail: function(e){ return '<div class="detail-row"><div class="k">Case report</div><div>'+caseReportCell(e, entries)+'</div></div>'; }
    })+
    '</div>';
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
        (u.username === state.user.username ? '<span class="muted" style="font-size:12px;">your account</span> ' :
          '<button class="btn btn-sm '+(u.active===false?"":"btn-danger")+'" data-toggle-active="'+esc(u.username)+'" data-next="'+(u.active===false?"true":"false")+'">'+(u.active===false?"Reactivate":"Deactivate")+'</button> ')+
        '<button class="btn btn-sm btn-danger" data-delete-user="'+esc(u.username)+'">Delete</button>'+
      '</td></tr>';
  }
  function renderUserAccountsTable(rows, canChangeRole){
    return '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Batch / Designation / Unit</th><th>Status</th><th></th></tr></thead><tbody>'+
      rows.map(function(u){ return userAccountRow(u, canChangeRole); }).join("")+
    '</tbody></table></div>';
  }

  function renderDeveloperUsers(){
    if(state.loading) return skeletonTable(5);
    var rows = state.devUsers.slice().sort(function(a,b){ return (a.username).localeCompare(b.username); });
    return ''+
    renderCreateUserForm()+
    '<div class="card"><h2>All accounts ('+rows.length+')</h2>'+
    renderUserAccountsTable(rows, true)+
    '</div>';
  }

  function renderManageUsers(){
    if(state.loading) return skeletonTable(5);
    var rows = state.manageUsers.slice().sort(function(a,b){ return (a.username).localeCompare(b.username); });
    return ''+
    '<div class="card"><h2>Manage accounts ('+rows.length+')</h2>'+
      '<p class="muted" style="margin-bottom:14px;">Update a trainee’s batch as they progress, or a consultant’s designation on promotion, and deactivate or delete accounts that no longer need access. Role changes and password resets stay Developer-only.</p>'+
      renderUserAccountsTable(rows, false)+
    '</div>';
  }

  function renderSignupApprovals(){
    if(state.loading) return skeletonTable(5);
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
    if(state.loading) return skeletonDash();
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
      (pending.length===0 ? '<div class="empty-state">'+artPlate("ossicles","es-plate")+'Nothing waiting.</div>' :
      '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Note</th><th>Requested</th><th></th></tr></thead><tbody>'+pending.map(function(r){return reqRow(r,true);}).join("")+'</tbody></table></div>')+
    '</div>'+
    (resolved.length ? '<div class="card"><h2 style="font-size:15px;">Resolved</h2>'+
      '<div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Note</th><th>Requested</th><th></th></tr></thead><tbody>'+resolved.map(function(r){return reqRow(r,false);}).join("")+'</tbody></table></div>'+
    '</div>' : '');
  }

  function renderDeveloperData(){
    if(state.loading) return skeletonDash();
    var traineeCount = state.devUsers.filter(function(u){return isTraineeRole(u.role);}).length;
    var consultantCount = state.devUsers.filter(function(u){return u.role==="consultant";}).length;
    var devCount = state.devUsers.filter(function(u){return u.role==="developer";}).length;
    var orph = state.unitOrphans;
    var orphanCard = "";
    if(orph && ((orph.orphans && orph.orphans.length) || orph.unattributedEntries)){
      var rows = (orph.orphans||[]).map(function(o){
        return '<tr><td class="mono">'+esc(o.unit)+'</td><td class="tabular">'+o.entries+'</td>'+
               '<td class="tabular">'+o.postings+'</td><td class="tabular">'+o.users+'</td>'+
               '<td class="tabular">'+o.assignments+'</td></tr>';
      }).join("");
      orphanCard =
        '<div class="card"><div class="section-head"><h2>Unit references that no longer resolve</h2></div>'+
        '<p class="muted" style="margin-bottom:12px;">The unit on an entry is what every Head of Unit roster and unit CSV filters on. '+
        'Anything listed here is filed under a key this department does not have, so it is invisible to unit-scoped consultants \u2014 '+
        'though a Head of Department or Course Coordinator still sees it, since their scope is not filtered by unit. '+
        'This normally means a unit was deleted from Manage Lists while records still referenced it.</p>'+
        (rows ? '<div class="table-wrap"><table><thead><tr><th>Unit key</th><th>Entries</th><th>Postings</th>'+
                '<th>People</th><th>Assignments</th></tr></thead><tbody>'+rows+'</tbody></table></div>' : '')+
        (orph.unattributedEntries ?
          '<div class="notice-banner" style="margin-top:14px;"><span>'+orph.unattributedEntries+
          ' finalised '+(orph.unattributedEntries===1?'entry has':'entries have')+' no unit at all \u2014 logged before a posting was added. '+
          'Same effect on a roster, but an ordinary one rather than a sign of anything wrong.</span></div>' : '')+
        '<p class="muted" style="margin-top:12px; font-size:12.5px;">To fix: re-add the unit under '+
        '<b>Units &amp; Roles</b> with the same key, or edit the affected postings.</p>'+
        '</div>';
    }
    return ''+
    '<div class="stat-grid">'+
      statTile(state.devAllEntries.length,"Total entries")+
      statTile(traineeCount,"Trainees")+
      statTile(consultantCount,"Consultants")+
      statTile(devCount,"Developers")+
    '</div>'+
    orphanCard+
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
  // Adding a department's diagnosis list one box-and-button at a time is
  // forty round trips. Paste the block, see exactly what will happen, then
  // commit -- the preview matters more than the paste, because a silent
  // merge into a list everyone selects from is hard to unpick afterwards.
  function bulkAddPanel(title){
    var p = state.bulkList.preview;
    return '<div class="acct-panel">'+
      '<div class="exp-sub">Bulk add to “'+esc(title)+'”</div>'+
      '<p class="muted" style="font-size:12.5px; margin:-2px 0 8px;">'+
        'One per line, or separated by commas or semicolons. Anything already in the list is skipped.</p>'+
      '<textarea id="bulk-text" rows="6" placeholder="Tympanoplasty – Type 1&#10;Tympanoplasty – Type 2&#10;Cortical mastoidectomy">'+
        esc((state.bulkList.text)||"")+'</textarea>'+
      (p ? '<div class="bulk-preview">'+
          '<div><b>'+p.added.length+'</b> to add'+
            (p.alreadyPresent.length ? ' · <span class="muted">'+p.alreadyPresent.length+' already in the list</span>' : '')+
            (p.repeatedInPaste.length ? ' · <span class="muted">'+p.repeatedInPaste.length+' repeated in the paste</span>' : '')+
            ' · list becomes <b>'+p.total+'</b></div>'+
          (p.added.length ? '<div class="bulk-chips">'+p.added.slice(0,40).map(function(x){
              return '<span class="chip chip-green">'+esc(x)+'</span>'; }).join("")+
              (p.added.length>40 ? '<span class="muted"> +'+(p.added.length-40)+' more</span>' : '')+'</div>' : '')+
          (p.alreadyPresent.length ? '<div class="bulk-chips">'+p.alreadyPresent.slice(0,20).map(function(x){
              return '<span class="chip chip-grey">'+esc(x)+'</span>'; }).join("")+'</div>' : '')+
        '</div>' : '')+
      '<div class="btn-row"><button class="btn btn-sm" id="bulk-close">Cancel</button>'+
        '<span style="display:flex; gap:8px;">'+
          '<button class="btn btn-sm" id="bulk-preview">Check</button>'+
          '<button class="btn btn-sm btn-primary" id="bulk-apply"'+(p && p.added.length?'':' disabled')+'>'+
            (p && p.added.length ? 'Add '+p.added.length : 'Add')+'</button>'+
        '</span></div>'+
    '</div>';
  }

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
          '<button class="btn btn-sm" data-bulk-open="'+spec.key+'">Bulk add…</button>'+
        '</div>'+
        (state.bulkList && state.bulkList.key===spec.key ? bulkAddPanel(spec.title) : '')+
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
      // Repair path for catalogues that lost their lists to the old
      // whole-map overwrite. Adds back only what is missing, so a site the
      // department has curated keeps everything it already has.
      '<div style="border-top:1px dashed var(--line); margin-top:14px; padding-top:12px; display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;">'+
        '<span class="muted" style="font-size:12.5px; max-width:60ch;">Missing procedures a site used to have? This puts the shipped lists back for every site, without removing anything you have added.</span>'+
        '<button class="btn btn-sm" id="restore-procs">Restore default procedure lists</button>'+
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
    if(state.loading) return skeletonDash();
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

    // Who currently holds each appointment, side by side. There is no limit
    // of one per role -- several people can be Course Coordinator at the
    // same time, and always could -- but reading that off a date-sorted
    // history was work.
    var holders = ["hod","coordinator","head_of_unit"].map(function(r){
      var live = state.roleAssignments.filter(function(a){ return a.role===r && isAssignmentActive(a); });
      return '<div class="holder-col"><div class="exp-sub">'+esc(roleTypeLabel[r])+'</div>'+
        (live.length ? live.map(function(a){
            return '<div class="member"><span class="member-name">'+esc(a.consultantDisplayName||a.consultantUsername)+'</span>'+
              '<span class="muted">'+(a.unit?esc(unitShort(a.unit)):"All units")+
              (a.endAt?' · to '+fmtDate(String(a.endAt).slice(0,10)):'')+'</span></div>';
          }).join("")
          : '<p class="muted" style="font-size:13px;">Nobody appointed.</p>')+
      '</div>';
    }).join("");

    return ''+
    '<div class="card"><h2 style="font-size:15px;">Who holds what today</h2>'+
      '<p class="muted" style="font-size:12.5px; margin-top:-8px; margin-bottom:12px;">'+
        'Appointments in force right now. More than one person can hold the same role at once.</p>'+
      '<div class="holder-grid">'+holders+'</div>'+
    '</div>'+
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
  /* ============================================================
     CHANGELOG

     Hardcoded rather than stored in the config table on purpose. A
     changelog describes the BUILD -- the code the browser is actually
     running -- so keeping it in the database would let the two drift:
     restore an older database and the log would claim features the code
     no longer has. It ships with the file it describes, so it cannot lie.

     Newest first. Dates are build dates, not deployment dates -- when a
     release reached the live site is up to whoever deployed it.
     Types: "added" | "changed" | "fixed".
  ============================================================ */
  var CHANGELOG = [
    {
      version: "7.0", date: "2026-09-26", title: "Accounts, edit locking and bulk lists",
      note: "Records can no longer be edited by two people at once, and leaving the department is now something the app handles properly.",
      changes: [
        ["added", "<b>A record being edited is locked to everyone else.</b> Open one and it is yours; anyone else is told who has it and since when. The lock lapses on its own after 10 minutes, so a closed laptop never strands a record."],
        ["fixed", "<b>Two people editing the same record no longer lose each other’s work.</b> A save is refused if the record moved while you were typing, and you are told to reopen it. Previously the second save silently overwrote the first — and the edit history then claimed a change that had not been kept."],
        ["added", "<b>The department can never be left without a Developer.</b> The last one cannot be deleted, deactivated or moved to another role, by themselves or anyone else."],
        ["added", "<b>Deactivate your own account</b> from My Account — immediate, for long leave or a sabbatical, and <b>reversed simply by signing in again</b>. An account an admin switched off still needs an admin to switch it back on. Reasons are a list the Developer can edit."],
        ["added", "<b>Closing an account properly.</b> You ask, with a reason; the Head of Department decides for a trainee, either they or a Developer for anyone else; then a <b>14-day countdown</b> that you or they can stop at any point. Nothing is destroyed before it runs out."],
        ["added", "<b>Closing an account never removes the work.</b> Entries, sign-offs and a consultant’s name on an operation record all stay exactly where they are, flagged as a closed account. Those records are somebody else’s evidence."],
        ["added", "<b>A full copy of a closed account</b> — profile, entries, postings, sign-offs given, the lot — is taken the moment closure is approved and can be downloaded by the Developer. They can also restore the login afterwards."],
        ["added", "<b>An Account Requests screen</b> for the Head of Department, Course Coordinator and Developer: what is waiting, what is counting down and how long is left, and who is currently deactivated and whether they switched themselves off."],
        ["added", "<b>Bulk add to any list.</b> Paste a block of options, see exactly what is new, what is already there and what you repeated, then commit."],
        ["changed", "<b>My Account rebuilt</b>: your details, your appointments with how long each has run, your postings, everyone else in your unit, and a password change condensed to one row."],
        ["added", "<b>Units & Roles shows who holds what today</b>, side by side. More than one person can be Course Coordinator at the same time — that has always been true and is now visible."],
        ["added", "Every account change — who asked, who decided, when and why — is recorded permanently, so it stays answerable after the account itself is gone."],
      ],
    },
    {
      version: "6.1", date: "2026-09-26", title: "Pre-presentation bug audit",
      note: "A full pass over the code before showing it to the department: authorisation, malformed input, the approval clock, and how it behaves on a phone.",
      changes: [
        ["fixed", "<b>One malformed request could stop every save in the whole app.</b> When a write failed part-way, the database connection was left holding a lock and handed back to the next request still holding it. Reads kept working, so the app looked fine while refusing to save anything — and under the production server it would not have recovered on its own. Now every request releases its connection whether it succeeded or not."],
        ["fixed", "<b>About thirty ways to make the server error out</b> — an unexpected value in almost any field, including on the sign-in and sign-up screens, which need no account at all. Every field is now checked before it reaches the database, and an unexpected error shows a plain message instead of a page of code."],
        ["fixed", "<b>A Head of Department could give any consultant sight of a unit’s records</b> by setting their designation to Professor, bypassing the audited appointment screen. Designation is now Developer-only, because it decides what someone can see. Batch changes stay with the Head of Department."],
        ["fixed", "<b>A Head of Department could deactivate or delete the Developer account</b>, locking out the only role that can manage accounts, units and lists."],
        ["fixed", "<b>A consultant with no unit access could still look up any account by name</b>, including the Developer’s. Now scoped like everything else."],
        ["fixed", "<b>A developer could read a trainee’s unfinished draft</b> through the edit route, which the view route has always refused."],
        ["fixed", "<b>An invalid date saved on an existing entry broke that trainee’s dashboard permanently</b>, with no way back to the entry to fix it. Invalid dates are now refused."],
        ["fixed", "<b>A record reopened by an edit arrived already flagged overdue</b> and escalated to the Head of Unit on day one, because the waiting clock still ran from the original submission. It now restarts whenever a record lands back in a consultant’s queue."],
        ["fixed", "<b>A withdrawn record still named the consultant it had been sent to</b>, in the list and in exports."],
        ["fixed", "<b>An already-signed record could be signed a second time</b>, putting a duplicate signature in its history."],
        ["fixed", "<b>A case write-up could be linked to another trainee’s operation.</b> It can now only be linked to one of your own."],
        ["fixed", "<b>Three fast clicks on a Send button created three records.</b> Every action that saves is now guarded against firing twice."],
        ["fixed", "<b>Every screen scrolled sideways on a phone.</b> The culprit was the top bar, not the content — it now drops the wordmark and role badge on a narrow screen and fits."],
        ["fixed", "Escape closed two of the five dialogs; it now closes all of them. Buttons, menus and form fields are bigger on touch screens."],
        ["fixed", "Appointment start and end dates were compared against UTC rather than local time, so a Head of Unit appointed today had no access until the small hours, and an appointment ending today expired a day early."],
        ["fixed", "An unapproved sign-up appeared in everyone’s “send for sign-off” list. Invalid settings could be saved and then break sign-up and account creation; they are now refused."],
        ["changed", "Long text is capped at a sensible length per field, a record can cover at most twelve sites, and the approval screens have database indexes so they stay fast as the department’s history grows."],
      ],
    },
    {
      version: "6.0", date: "2026-09-26", title: "Roster, export builder and feedback",
      note: "Three additions asked for by the department, plus two roster faults found while building them \u2014 one of them a consultant seeing more than their unit.",
      changes: [
        ["fixed", "<b>A Head of Unit could read a trainee’s work in every other unit.</b> Opening a trainee checked whether you were allowed to open them and then returned their entire logbook, every unit included. A unit’s consultant now sees only what was logged during that trainee’s postings in their unit — on the roster, on the trainee’s page, in the charts and in exports alike."],
        ["fixed", "<b>“Current unit” in the roster has never shown anything.</b> The roster was built from a user record that does not carry postings, so the lookup always came back empty and every trainee showed a dash."],
        ["changed", "<b>The roster now lists everyone who has ever been posted to your unit</b>, not only those who have logged something there. Someone who logged nothing during their rotation is exactly who a roster should surface, and a trainee due to arrive is listed as upcoming."],
        ["changed", "<b>“Last entry” is replaced by time in the unit.</b> A Head of Unit sees how long each trainee has served in their unit, across repeat rotations, with a booked return shown underneath. The Head of Department and Course Coordinator see the posting the trainee is on today instead, wherever that is."],
        ["added", "<b>“Currently in”</b> — where each trainee is posted today, shown to everyone. A Head of Unit is told that one fact about units they do not oversee, so the department always knows where people are, without being given anyone’s rotation history."],
        ["added", "<b>A postings panel</b> on a trainee’s page, listing each block with its dates, time served and whether it is completed, current or upcoming. A Head of Unit sees their own unit’s blocks; the Head of Department and Course Coordinator see all of them."],
        ["changed", "<b>The roster shows a unit consultant and Head of Unit the operative columns only</b> — Total, Surgical, Other and Cases. Academic and Seminars are shown to the Head of Department and Course Coordinator, who oversee the teaching record. The same applies to the tiles on a trainee’s page."],
        ["added", "<b>An export builder.</b> Choose which entries go in the file — by type, date range, unit, trainee or sign-off state — and which of the 29 columns it has, with presets for an operative log, case write-ups and a teaching record. Columns always come out in the same order, so two exports of the same fields line up. Your choices are remembered in your browser."],
        ["added", "<b>Feedback, complaints and suggestions</b>, read only by the Head of Department, the Course Coordinator and the Developer admin. Send it under your name and you can follow its status; send it anonymously and no author is stored at all, so nobody can look it up afterwards — and for the same reason nobody can reply to you."],
        ["added", "Whoever handles a submission marks it Open, Being looked at or Closed, and can keep internal notes on it. The person who sent it sees the status, never the notes."],
      ],
    },
    {
      version: "5.0", date: "2026-09-25", title: "Live-site bug audit",
      note: "Six defects found by testing the deployed site and reproduced against the same code before fixing.",
      changes: [
        ["fixed", "<b>Procedure lists could be wiped by editing one site.</b> Saving a single site’s procedures under Manage Lists replaced the whole procedure map and deleted every other site’s list. This had already happened on the live site: 63 of 65 procedures were gone, leaving nose, throat, head-and-neck, skull-base and trauma cases impossible to log. The server now merges each site separately."],
        ["added", "<b>Restore default procedure lists</b> under Manage Lists — puts back any shipped procedure a site has lost, without removing anything the department has added itself."],
        ["fixed", "<b>A signed-off record could be permanently deleted</b> by a Developer, taking the consultant’s signature and the whole sign-off history with it. Now refused for everyone; the record has to be released first."],
        ["fixed", "<b>Re-sending a record already awaiting sign-off silently moved it to a different consultant</b>, and the first consultant’s queue lost it with no trace. Re-sending to the same consultant is now refused; a genuine change of approver is recorded as a reassignment naming both."],
        ["fixed", "<b>Records logged on a date with no posting were invisible to oversight.</b> They carry no unit, so they never appeared in the overdue panel and could not be signed off by a Head of Unit acting as delegate. Overdue ones now surface to anyone with an oversight role."],
        ["fixed", "“Ask to unlock” accepted a blank reason, so it reached a consultant as a bare flag with nothing to act on. A reason is now required, as it already was for “Ask for changes”."],
        ["fixed", "Pressing Enter in the username box did nothing — only the password box submitted. Both now work, on sign-in and Developer sign-in."],
        ["fixed", "Removing a site left its procedure list behind in the configuration, and it reappeared if a site with the same key was ever created again."],
      ],
    },
    {
      version: "4.0", date: "2026-09-25", title: "Consultant sign-off",
      note: "Operative records and case write-ups are attested by a named consultant. Academic and Seminar entries are untouched — they are the trainee’s own attendance record and nobody signs for them.",
      changes: [
        ["added", "<b>Send for sign-off.</b> A trainee finalises a record and nominates the consultant who should sign it. A linked Interesting Case and its parent operation are two independent approvals — signing one never signs the other."],
        ["added", "<b>Case Sign-off queue</b> for consultants: approve, or send back with a required note explaining what needs changing."],
        ["added", "<b>Approved records are locked.</b> The consultant attested to one specific version, so the trainee cannot edit or delete it afterwards. They can ask for an unlock; the approver (or a Head of Unit / Coordinator / HOD) releases it."],
        ["added", "<b>Bulk send and bulk sign-off</b>, up to 200 records at a time — the back-catalogue path, so a department’s existing history can be opted in gradually rather than landing in every consultant’s queue on day one."],
        ["added", "<b>Sign-off counters</b> on the trainee dashboard and the entries list, plus a full per-record sign-off history."],
        ["added", "<b>Escalation after 7 days.</b> Anything waiting longer shows on the dashboard of every Head of Unit, Coordinator and HOD with oversight of that unit, so one consultant being away cannot stall a trainee’s logbook."],
        ["changed", "Editing a signed record in a way that changes the case itself returns it to “awaiting sign-off” automatically. Comments and write-up status do not."],
      ],
    },
    {
      version: "3.0", date: "2026-09-23", title: "Interface review and 23 fixes",
      note: "A pass over the whole site for appearance, motion and defects.",
      changes: [
        ["fixed", "<b>The row action menu was 94% invisible</b> — the card it sat inside was clipping it, so only a sliver of the menu could ever be seen."],
        ["fixed", "<b>Adding one procedure deleted every other site’s list</b> in the browser. (The server-side half of this same bug was not caught until 5.0 — see above.)"],
        ["fixed", "<b>A draft could be read by anyone who guessed its number.</b> Entry ids run in sequence, so the department’s unfinished entries were enumerable. A draft now belongs to its author alone."],
        ["fixed", "<b>A unit name could inject code into the consultant scope banner.</b> Closed."],
        ["fixed", "<b>A rejected profile edit still saved part of itself.</b> The refused request left its privileged writes behind for the next request to commit."],
        ["fixed", "<b>The Consultant dashboard was stuck on “Loading…”</b> for anyone who was a Head of Department or Course Coordinator."],
        ["fixed", "<b>A resident could hide their logbook</b> by logging entries against a unit they were never posted to. The unit is now stamped from the posting that covers the entry’s date and cannot be chosen by hand."],
        ["fixed", "Contrast failures throughout, including a focus ring that was invisible against its own button, and unreadable placeholder text."],
        ["added", "<b>Dark mode.</b> It had been written but was unreachable — nothing ever switched it on. There is now a toggle in the top bar cycling automatic / light / dark."],
        ["added", "Transitions and entry animations, with a full <i>reduced motion</i> path for anyone whose system asks for one."],
        ["added", "Loading skeletons in place of bare “Loading…” text."],
        ["added", "A Developer report of records pointing at units the department no longer has, and of records logged with no posting at all."],
      ],
    },
    {
      version: "2.0", date: "2026-09-23", title: "Artwork, icons and palette",
      changes: [
        ["added", "<b>A drawn icon set</b> — nineteen icons rebuilt on a single grid so they sit at a consistent weight beside each other."],
        ["added", "<b>A photographic sign-in screen</b>, served from this server rather than fetched from outside it."],
        ["added", "<b>Anatomical watercolour plates</b> across the dashboard, site categories and empty states."],
        ["changed", "<b>The colour scheme is now taken from the artwork</b> rather than the artwork being recoloured to match a palette chosen beforehand."],
      ],
    },
    {
      version: "1.0", date: "2026-09-21", title: "First working logbook",
      changes: [
        ["added", "Five entry types: Surgical Procedure, Other Procedure, Interesting Case, Academic Participation, Seminar / Presentation."],
        ["added", "Date-based unit postings, so every entry permanently carries the unit that was active on its date."],
        ["added", "Resident, Consultant and Developer views, with Head of Unit / Course Coordinator / HOD appointments."],
        ["added", "Progress statistics, CSV export, and a full per-entry edit history."],
      ],
    },
  ];
  var APP_VERSION = CHANGELOG[0].version;

  var CHANGE_TAG = {
    added:   ["New",     "chip-green"],
    changed: ["Changed", "chip-teal"],
    fixed:   ["Fixed",   "chip-amber"],
  };

  function renderChangelog(){
    return '<div class="card"><div class="section-head"><h2>Updates</h2>'+
      '<span class="chip chip-grey">Running version '+esc(APP_VERSION)+'</span></div>'+
      '<p class="muted" style="font-size:12.5px; margin:-6px 0 16px;">Every release, newest first, and what changed in it. '+
        'Dates are when the release was built — ask your Developer admin when it reached this server.</p>'+
      '<ol class="chl">'+CHANGELOG.map(function(r){
        return '<li class="chl-rel">'+
          '<div class="chl-head">'+
            '<span class="chl-ver">v'+esc(r.version)+'</span>'+
            '<b>'+esc(r.title)+'</b>'+
            '<span class="chl-date tabular">'+fmtDate(r.date)+'</span>'+
          '</div>'+
          (r.note ? '<p class="chl-note muted">'+r.note+'</p>' : '')+
          '<ul class="chl-items">'+r.changes.map(function(c){
            var tag = CHANGE_TAG[c[0]] || CHANGE_TAG.changed;
            return '<li><span class="chip '+tag[1]+' chl-tag">'+tag[0]+'</span><span>'+c[1]+'</span></li>';
          }).join("")+'</ul>'+
        '</li>';
      }).join("")+'</ol></div>';
  }

  /* ============================================================
     FEEDBACK / COMPLAINTS / SUGGESTIONS

     Anyone with an account can raise one; only Head of Department, Course
     Coordinator and Developer can read them.

     Anonymity here is real, not a display flag: an anonymous submission
     stores no author at all, so nobody -- including a Developer with
     database access -- can look up who sent it. The price is that an
     anonymous submission cannot be tracked or followed up, which the form
     says plainly before the choice is made rather than after.
  ============================================================ */
  var FEEDBACK_KINDS = [
    ["suggestion","Suggestion","Something that would make this better."],
    ["feedback","Feedback","How something is working in practice."],
    ["complaint","Complaint","Something that needs to be looked into."],
    ["bug","Something broken","The app itself is misbehaving."],
  ];
  var FEEDBACK_STATUS = {
    open:        ["Open",        "chip-amber"],
    in_progress: ["Being looked at","chip-teal"],
    closed:      ["Closed",      "chip-green"],
  };
  function canReadFeedback(){
    var caps = state.capabilities || {};
    return !!(caps.isHod || caps.isCoordinator || caps.isDeveloper);
  }
  function feedbackStatusChip(s){
    var d = FEEDBACK_STATUS[s] || FEEDBACK_STATUS.open;
    return '<span class="chip '+d[1]+'">'+esc(d[0])+'</span>';
  }
  function feedbackKindLabel(k){
    var m = FEEDBACK_KINDS.filter(function(x){ return x[0]===k; })[0];
    return m ? m[1] : k;
  }

  function renderFeedbackCompose(){
    var f = state.feedbackDraft;
    return '<div class="card"><h2>Raise something</h2>'+
      '<p class="muted" style="font-size:13px; margin-top:-6px; margin-bottom:14px;">'+
        'Read only by the Head of Department, the Course Coordinator and the Developer admin. '+
        'Not by your unit consultant, and not by anyone else on the roster.</p>'+
      '<div class="field"><label>What kind of message is this?</label><div class="radio-group">'+
        FEEDBACK_KINDS.map(function(k){
          return radioCard("fb-kind",k[0],f.kind===k[0],k[1],k[2]);
        }).join("")+
      '</div></div>'+
      '<div class="field"><label for="fb-subject">Subject</label>'+
        '<input id="fb-subject" type="text" maxlength="200" placeholder="One line — what is this about?" value="'+esc(f.subject||"")+'"></div>'+
      '<div class="field"><label for="fb-body">Message</label>'+
        '<textarea id="fb-body" rows="6" placeholder="What happened, or what would you change?">'+esc(f.body||"")+'</textarea></div>'+
      '<div class="field"><label>Send this as</label><div class="radio-group">'+
        radioCard("fb-anon","named",!f.anonymous,"My name",
          "They can come back to you for detail, and you can follow the status under “What I have raised”.")+
        radioCard("fb-anon","anon",!!f.anonymous,"Anonymously",
          "Your name is never stored, so nobody can look it up afterwards — and for the same reason nobody can reply to you, and you will not be able to track it.")+
      '</div></div>'+
      (f.anonymous ? '<div class="notice-banner"><span>Once you send this anonymously it leaves no link back to you at all. '+
        'If you may want to add to it later, or want an answer, send it under your name instead.</span></div>' : '')+
      '<div class="btn-row"><span></span>'+
        '<button class="btn btn-primary" id="fb-send"'+(state.feedbackBusy?" disabled":"")+'>'+
          (state.feedbackBusy?'<span class="spin"></span>Sending…':'Send')+'</button></div>'+
    '</div>';
  }

  function renderFeedbackMine(){
    var rows = state.feedbackMine;
    if(rows==null) return "";
    return '<div class="card"><h2 style="font-size:15px;">What I have raised</h2>'+
      '<p class="muted" style="font-size:12.5px; margin-top:-6px; margin-bottom:12px;">'+
        'Named submissions only — anything you sent anonymously does not appear here, by design.</p>'+
      (rows.length ? '<div class="fb-list">'+rows.map(function(r){
        return '<div class="fb-row"><div class="fb-main">'+
          '<div class="fb-top"><span class="chip chip-grey">'+esc(feedbackKindLabel(r.kind))+'</span>'+
            '<b>'+esc(r.subject)+'</b></div>'+
          '<div class="fb-body muted">'+esc(r.body)+'</div>'+
          '<div class="fb-meta muted">Sent '+fmtDateTime(r.createdAt)+'</div>'+
        '</div><div>'+feedbackStatusChip(r.status)+'</div></div>';
      }).join("")+'</div>'
        : '<p class="muted" style="font-size:13px;">Nothing yet.</p>')+
    '</div>';
  }

  function renderFeedbackInbox(){
    var data = state.feedbackInbox;
    if(!data) return '<div class="card"><div class="empty-state">Loading…</div></div>';
    var rows = data.feedback || [], counts = data.counts || {};
    var filter = state.feedbackFilter || "";
    return '<div class="card"><div class="section-head"><h2>Inbox</h2>'+
        '<div class="pick-row" style="margin:0;">'+
          ['','open','in_progress','closed'].map(function(s){
            var label = s ? FEEDBACK_STATUS[s][0] : "All";
            var n = s ? (counts[s]||0) : (rows.length && !filter ? rows.length : (counts.open||0)+(counts.in_progress||0)+(counts.closed||0));
            return '<button type="button" class="btn btn-sm'+(filter===s?" btn-primary":"")+'" data-fb-filter="'+s+'">'+esc(label)+' ('+n+')</button>';
          }).join("")+
        '</div></div>'+
      (rows.length ? '<div class="fb-list">'+rows.map(function(r){
        var open = state.feedbackOpenId===r.id;
        return '<div class="fb-row'+(open?" open":"")+'">'+
          '<div class="fb-main">'+
            '<div class="fb-top">'+
              '<span class="chip chip-grey">'+esc(feedbackKindLabel(r.kind))+'</span>'+
              '<b>'+esc(r.subject)+'</b>'+
              (r.anonymous ? '<span class="chip chip-violet">Anonymous</span>' : '')+
            '</div>'+
            '<div class="fb-body'+(open?"":" muted")+'">'+esc(r.body)+'</div>'+
            '<div class="fb-meta muted">'+
              (r.anonymous ? 'No author recorded' : esc(r.authorDisplayName||r.authorUsername))+
              ' &middot; '+fmtDateTime(r.createdAt)+'</div>'+
            (open ? renderFeedbackDetail(r) : '')+
          '</div>'+
          '<div class="fb-side">'+feedbackStatusChip(r.status)+
            '<button class="btn btn-sm" data-fb-open="'+r.id+'">'+(open?"Close":"Handle")+'</button>'+
          '</div>'+
        '</div>';
      }).join("")+'</div>'
        : '<div class="empty-state">Nothing here.</div>')+
    '</div>';
  }

  function renderFeedbackDetail(r){
    var notes = (state.feedbackNotes||{})[r.id];
    return '<div class="fb-detail">'+
      '<div class="fb-actions">'+
        Object.keys(FEEDBACK_STATUS).map(function(s){
          return '<button type="button" class="btn btn-sm'+(r.status===s?" btn-primary":"")+'" data-fb-status="'+r.id+'" data-fb-value="'+s+'">'+esc(FEEDBACK_STATUS[s][0])+'</button>';
        }).join("")+
      '</div>'+
      '<div class="fb-notes">'+
        '<div class="exp-sub">Internal notes <span class="muted">— never shown to whoever sent this</span></div>'+
        (notes==null ? '<p class="muted" style="font-size:13px;">Loading…</p>' :
          (notes.length ? notes.map(function(n){
            return '<div class="fb-note"><div class="fb-note-meta muted">'+
              esc(n.actorDisplayName||n.actorUsername)+' &middot; '+fmtDateTime(n.createdAt)+
              (n.action==="status" ? ' &middot; marked '+esc((FEEDBACK_STATUS[n.status]||["?"])[0]) : '')+
              '</div>'+(n.note ? '<div>'+esc(n.note)+'</div>' : '')+'</div>';
          }).join("") : '<p class="muted" style="font-size:13px;">No notes yet.</p>'))+
        '<div style="display:flex; gap:8px; margin-top:10px;">'+
          '<input type="text" id="fb-note-'+r.id+'" placeholder="Add a note…" style="flex:1;">'+
          '<button class="btn btn-sm" data-fb-note="'+r.id+'">Add</button>'+
        '</div>'+
      '</div>'+
    '</div>';
  }

  function renderFeedback(){
    if(state.loading) return skeletonDash();
    return renderFeedbackCompose()+
      (canReadFeedback() ? renderFeedbackInbox() : "")+
      renderFeedbackMine();
  }

  function renderAbout(){
    return ''+
    '<div class="about-hero"><span class="hero-art a-theatre"></span>'+
      '<h2>About this logbook</h2>'+
      '<p>Built for the Department of Otorhinolaryngology. De-identified by design — every entry is logged against a Hospital Number, never a name.</p>'+
    '</div>'+
    '<div class="card"><h2>What this is</h2>'+
      '<p class="muted">A shared ENT logbook — a Dashboard homepage, five entry types (Surgical Procedure, Other Procedure, Interesting Case, Academic Participation, Seminar / Presentation), date-based unit postings, and role-based views (Resident / Consultant / Developer) — running on its own server and database, independent of any third-party platform.</p>'+
    '</div>'+
    renderChangelog()+
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
      '<li><b>“Procedure performed” is filtered by the Site you pick</b>, and the list is fixed — there is no free-text box. A case that genuinely spans sites gets a second site block (“Add another site”), each with its own procedures, laterality and role. If a procedure you need is missing from a site, ask your Developer admin to add it under Manage Lists.</li>'+
      '<li><b>Consultants sign off records, they do not rewrite them.</b> A consultant can approve a record or send it back with a note; correcting it is the trainee’s job, which is what keeps the logbook the trainee’s own account of the case.</li>'+
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
  var __entlogLastView = null;
  function render(){
    var app = el("app");
    if(!app) return;
    if(!state.capReady){
      app.innerHTML = authShell('<div class="auth-eyebrow">Loading</div>'+
        '<h1 style="font-size:20px;">Opening the logbook…</h1>', { center: true });
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
    else if(state.view==="approval-queue") inner = renderApprovalQueue();
    else if(state.view==="feedback") inner = renderFeedback();
    else if(state.view==="account-requests") inner = renderAccountRequests();
    else if(state.view==="about") inner = renderAbout();
    app.innerHTML = renderShell(inner) + (state.viewingEntryId ? renderEntryDetailModal() : "")
      + (state.viewingHistoryEntryId!=null ? renderEntryHistoryModal() : "")
      + renderSubmitDialog() + renderDecideDialog() + renderExportDialog();
    // THE GATE. render() runs on every state change -- every keystroke in a
    // filter, every checkbox -- and replaces the entire DOM, so an entry
    // animation attached to these elements would re-fire constantly and the
    // list would strobe while you type. Only a real view change animates.
    var main = app.querySelector("main");
    if(main && state.view !== __entlogLastView) main.classList.add("view-enter");
    __entlogLastView = state.view;
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
    // Enter submits from EITHER field. There is no <form> anywhere in this
    // app (every screen is innerHTML-rendered), so nothing gives implicit
    // submit for free -- and typing a username then hitting Enter, which is
    // what most people do, did nothing at all.
    ["login-username","login-password"].forEach(function(id){
      var f = el(id);
      if(f) f.addEventListener("keydown", function(ev){ if(ev.key==="Enter"){ ev.preventDefault(); el("btn-login").click(); } });
    });

    var goDevLogin = el("go-devlogin"); if(goDevLogin) goDevLogin.onclick = function(){ state.authMode="dev-login"; state.authError=""; render(); };
    var goLoginFromDev = el("go-login-from-dev"); if(goLoginFromDev) goLoginFromDev.onclick = function(){ state.authMode="login"; state.authError=""; render(); };
    var btnDevLogin = el("btn-devlogin"); if(btnDevLogin) btnDevLogin.onclick = function(){
      doLogin(el("dev-username").value, el("dev-password").value, "developer");
    };
    ["dev-username","dev-password"].forEach(function(id){
      var f = el(id);
      if(f) f.addEventListener("keydown", function(ev){ if(ev.key==="Enter"){ ev.preventDefault(); el("btn-devlogin").click(); } });
    });

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
        finishEditing(); state.wiz = null;
        render();
        loadForView();
      };
    });
    var navToggle = el("btn-nav-toggle");
    if(navToggle) navToggle.onclick = function(){ state.mobileNavOpen = !state.mobileNavOpen; render(); };
    /* ---------------- approvals ---------------- */
    function pickIds(){ return Object.keys(state.approvalPick).filter(function(k){ return state.approvalPick[k]; }); }
    async function openSubmit(ids){
      // consultantsList is normally only fetched on the way into Log Entry;
      // the submit dialog can be opened straight from My Entries.
      await loadConsultants();
      var d = approverOptions();
      state.submitDialog = { ids: ids, approver: d.length===1 ? d[0].username : "" };
      render();
    }
    document.querySelectorAll("[data-send-approval]").forEach(function(b){
      b.onclick = function(){ state.openEntryMenu=null; openSubmit([b.getAttribute("data-send-approval")]); };
    });
    document.querySelectorAll("[data-withdraw]").forEach(function(b){
      b.onclick = async function(){
        state.openEntryMenu=null;
        try{ await aWithdraw(b.getAttribute("data-withdraw")); await loadMyEntries(); await refreshApprovalSummary();
             toast("Withdrawn from sign-off."); render(); }
        catch(e){ toast(e.message||"Could not withdraw."); }
      };
    });
    document.querySelectorAll("[data-request-unlock]").forEach(function(b){
      b.onclick = async function(){
        state.openEntryMenu=null;
        var why = window.prompt("What needs changing? Your consultant sees this.");
        if(why===null) return;
        try{ await aRequestUnlock(b.getAttribute("data-request-unlock"), why);
             toast("Unlock requested — it will show in their sign-off queue."); render(); }
        catch(e){ toast(e.message||"Could not send that."); }
      };
    });
    // The select-for-bulk checkbox lives INSIDE .entry-card-summary, which is
    // itself a button that expands the row. Without this, ticking a box also
    // expands the record and the resulting re-render races the change event,
    // so the tick appears to do nothing.
    document.querySelectorAll(".row-pick").forEach(function(lbl){
      lbl.onclick = function(ev){ ev.stopPropagation(); };
    });
    document.querySelectorAll("[data-pick],[data-qpick]").forEach(function(cb){
      cb.onclick = function(ev){ ev.stopPropagation(); };
      cb.onchange = function(){
        var id = cb.getAttribute("data-pick") || cb.getAttribute("data-qpick");
        var wasAny = pickIds().length > 0;
        if(cb.checked) state.approvalPick[id]=true; else delete state.approvalPick[id];
        var nowAny = pickIds().length > 0;
        // render() rebuilds the whole DOM, which on a 200-row list is a
        // visible stutter on every tick -- and it would also blow away the
        // checkbox the user just clicked. Only re-render when the bar has to
        // appear or disappear; otherwise update it in place.
        if(wasAny !== nowAny){ render(); return; }
        updateBulkBar();
      };
    });
    function updateBulkBar(){
      var count = pickIds().length;
      var bar = document.querySelector(".bulk-bar");
      if(!bar) return;
      var label = bar.querySelector("span");
      if(label) label.textContent = count + " selected";
      var send = bar.querySelector("[data-bulk-send]");
      if(send) send.textContent = "Send " + count + " for sign-off";
      var appr = bar.querySelector("[data-bulk-approve]");
      if(appr) appr.textContent = "Sign off " + count;
    }
    var pickClear = document.querySelector("[data-pick-clear]");
    if(pickClear) pickClear.onclick = function(){ state.approvalPick = {}; render(); };
    var bulkSend = document.querySelector("[data-bulk-send]");
    if(bulkSend) bulkSend.onclick = function(){ openSubmit(pickIds()); };
    var bulkApprove = document.querySelector("[data-bulk-approve]");
    if(bulkApprove) bulkApprove.onclick = once("bulk-approve", async function(){
      var ids = pickIds();
      if(!window.confirm("Sign off "+ids.length+" record"+(ids.length===1?"":"s")+"? They will be locked to further editing.")) return;
      try{
        var r = await aBulkApprove(ids);
        state.approvalPick = {};
        state.approvalQueue = await aQueue(); await refreshApprovalSummary();
        toast("Signed off "+r.approved.length+(r.skipped.length?" — "+r.skipped.length+" skipped":"")+".");
        render();
      }catch(e){ toast(e.message||"Could not sign those off."); }
    });
    document.querySelectorAll("[data-sign-off]").forEach(function(b){
      b.onclick = function(){ state.decideDialog = { id: b.getAttribute("data-sign-off"), action:"approve" }; render(); };
    });
    document.querySelectorAll("[data-ask-changes]").forEach(function(b){
      b.onclick = function(){ state.decideDialog = { id: b.getAttribute("data-ask-changes"), action:"changes" }; render(); };
    });
    document.querySelectorAll("[data-open-entry]").forEach(function(b){
      b.onclick = function(){ state.viewingEntryId = b.getAttribute("data-open-entry"); render(); };
    });
    document.querySelectorAll("[data-approval-history]").forEach(function(b){
      b.onclick = async function(){
        state.openEntryMenu=null;
        try{
          var h = await aHistory(b.getAttribute("data-approval-history"));
          toast(h.length ? h.map(function(r){ return r.action.replace(/_/g," ")+" by "+r.actor_username; }).join(" \u2192 ") : "No sign-off activity yet.");
        }catch(e){ toast(e.message||"Could not load that."); }
      };
    });
    // submit dialog
    document.querySelectorAll("[data-submit-cancel]").forEach(function(b){
      b.onclick = function(){ state.submitDialog=null; render(); };
    });
    var subOv = document.querySelector("[data-submit-overlay]");
    if(subOv) subOv.onclick = function(ev){ if(ev.target===subOv){ state.submitDialog=null; render(); } };
    var subGo = document.querySelector("[data-submit-go]");
    if(subGo) subGo.onclick = once("submit-approval", async function(){
      var who = (el("submit-approver")||{}).value || "";
      var note = (el("submit-note")||{}).value || "";
      if(!who){ toast("Pick a consultant to send this to."); return; }
      var ids = state.submitDialog.ids;
      subGo.disabled = true; subGo.innerHTML = '<span class="spin"></span>Sending…';
      try{
        if(ids.length===1) await aSubmit(ids[0], who, note);
        else await aBulkSubmit(ids, who);
        state.submitDialog=null; state.approvalPick={};
        await loadMyEntries(); await refreshApprovalSummary();
        toast(ids.length===1 ? "Sent for sign-off." : "Sent "+ids.length+" records for sign-off.");
        render();
      }catch(e){ subGo.disabled=false; subGo.textContent="Send"; toast(e.message||"Could not send that."); }
    });
    // decide dialog
    document.querySelectorAll("[data-decide-cancel]").forEach(function(b){
      b.onclick = function(){ state.decideDialog=null; render(); };
    });
    var decOv = document.querySelector("[data-decide-overlay]");
    if(decOv) decOv.onclick = function(ev){ if(ev.target===decOv){ state.decideDialog=null; render(); } };
    var decGo = document.querySelector("[data-decide-go]");
    if(decGo) decGo.onclick = once("decide-approval", async function(){
      var d = state.decideDialog, note = (el("decide-note")||{}).value || "";
      if(d.action==="changes" && !note.trim()){ toast("Say what needs changing."); return; }
      decGo.disabled = true; decGo.innerHTML = '<span class="spin"></span>Saving…';
      try{
        if(d.action==="approve") await aApprove(d.id, note); else await aRequestChanges(d.id, note);
        state.decideDialog=null;
        state.approvalQueue = await aQueue(); await refreshApprovalSummary();
        toast(d.action==="approve" ? "Signed off." : "Sent back with your note.");
        render();
      }catch(e){ decGo.disabled=false; decGo.textContent="Save"; toast(e.message||"Could not save that."); }
    });

    /* ---------------- account lifecycle ---------------- */
    document.querySelectorAll("[data-acct-action]").forEach(function(b){
      b.onclick = function(){ state.accountAction = b.getAttribute("data-acct-action") || null; render(); };
    });
    var doDeact = el("do-deactivate");
    if(doDeact) doDeact.onclick = once("deactivate", async function(){
      var reason = (el("deact-reason")||{}).value || "";
      var note = (el("deact-note")||{}).value || "";
      if(!window.confirm("Deactivate your account now? You will be signed out, and signing in again brings it straight back.")) return;
      try{
        await acctDeactivate(reason, note);
        toast("Deactivated. Sign in again whenever you are back.");
        setTimeout(function(){ doLogout(); }, 900);
      }catch(e){ toast(e.message || "Could not deactivate."); }
    });
    var doDel = el("do-request-deletion");
    if(doDel) doDel.onclick = once("request-deletion", async function(){
      var reason = (el("del-reason")||{}).value || "";
      if(!reason.trim()){ toast("Say why you are closing the account."); return; }
      if(!window.confirm("Send this for approval? Nothing is destroyed yet — you will still have 14 days to stop it after it is approved.")) return;
      try{
        var r = await acctRequestDeletion(reason);
        toast("Sent to "+r.needsApprovalFrom+"."+(r.entriesRetained?" Your "+r.entriesRetained+" logged entries stay on the system.":""));
        state.account = await acctOverview(); state.accountAction=null; render();
      }catch(e){ toast(e.message || "Could not send that."); }
    });
    var cancelDel = el("cancel-deletion");
    if(cancelDel) cancelDel.onclick = once("cancel-deletion", async function(){
      try{
        await acctCancelDeletion();
        toast("Closure stopped. Your account stays as it is.");
        state.account = await acctOverview(); render();
      }catch(e){ toast(e.message || "Could not stop it."); }
    });

    document.querySelectorAll("[data-acct-decide]").forEach(function(b){
      b.onclick = once("acct-decide", async function(){
        var id = b.getAttribute("data-acct-decide"), decision = b.getAttribute("data-decision");
        var note = "";
        if(decision === "approve"){
          if(!window.confirm("Approve this closure? The account is suspended immediately and destroyed after the buffer, unless somebody stops it. Their entries and sign-offs are kept either way.")) return;
        } else {
          note = window.prompt("Why are you refusing it? They will see this.") || "";
          if(!note.trim()) return;
        }
        try{
          await acctDecide(id, decision, note);
          state.accountRequests = await acctRequests();
          state.accountReqCount = (state.accountRequests.pending||[]).length;
          if((state.capabilities||{}).isDeveloper){ try{ state.accountArchives = await acctArchives(); }catch(e){} }
          toast(decision === "approve" ? "Approved — the countdown has started." : "Refused.");
          render();
        }catch(e){ toast(e.message || "Could not record that."); }
      });
    });
    document.querySelectorAll("[data-acct-cancel]").forEach(function(b){
      b.onclick = once("acct-cancel", async function(){
        try{
          await acctCancelDeletion(b.getAttribute("data-acct-cancel"));
          state.accountRequests = await acctRequests();
          state.accountReqCount = (state.accountRequests.pending||[]).length;
          toast("Closure stopped and the account is back.");
          render();
        }catch(e){ toast(e.message || "Could not stop it."); }
      });
    });
    document.querySelectorAll("[data-archive-dl]").forEach(function(b){
      b.onclick = function(){ window.location.href = "/api/account/archives/"+b.getAttribute("data-archive-dl")+".json"; };
    });
    document.querySelectorAll("[data-archive-restore]").forEach(function(b){
      b.onclick = once("acct-restore", async function(){
        var u = b.getAttribute("data-archive-restore");
        var pw = window.prompt("Set a new password for "+u+" (at least 8 characters). Their sign-in no longer exists, so restoring means giving them a new one.");
        if(pw === null) return;
        try{
          await acctRestore(u, pw);
          toast(u+" can sign in again.");
          state.accountRequests = await acctRequests(); render();
        }catch(e){ toast(e.message || "Could not restore that account."); }
      });
    });

    /* ---------------- bulk add to a list ---------------- */
    document.querySelectorAll("[data-bulk-open]").forEach(function(b){
      b.onclick = function(){ state.bulkList = { key: b.getAttribute("data-bulk-open"), preview: null }; render(); };
    });
    var bulkClose = el("bulk-close"); if(bulkClose) bulkClose.onclick = function(){ state.bulkList = null; render(); };
    var bulkPreview = el("bulk-preview");
    if(bulkPreview) bulkPreview.onclick = once("bulk-preview", async function(){
      var text = (el("bulk-text")||{}).value || "";
      if(!text.trim()){ toast("Paste the options first."); return; }
      try{
        state.bulkList.text = text;
        state.bulkList.preview = await bulkAddList(state.bulkList.key, text, true);
        render();
      }catch(e){ toast(e.message || "Could not read that."); }
    });
    var bulkApply = el("bulk-apply");
    if(bulkApply) bulkApply.onclick = once("bulk-apply", async function(){
      try{
        var r = await bulkAddList(state.bulkList.key, state.bulkList.text || (el("bulk-text")||{}).value || "", false);
        if(r.config) state.config = r.config;
        toast("Added "+r.added.length+" option"+(r.added.length===1?"":"s")+
              (r.alreadyPresent.length? " — "+r.alreadyPresent.length+" were already there" : "")+".");
        state.bulkList = null; render();
      }catch(e){ toast(e.message || "Could not add those."); }
    });

    var themeBtn = el("btn-theme"); if(themeBtn) themeBtn.onclick = cycleTheme;
    // role="button" is a promise that Enter and Space work; keep it.
    document.querySelectorAll('[role="button"][tabindex="0"]').forEach(function(nd){
      nd.onkeydown = function(ev){
        if(ev.key === "Enter" || ev.key === " "){ ev.preventDefault(); nd.click(); }
      };
    });
    // Escape closes whichever modal is open.
    if(!window.__entlogEscBound){
      window.__entlogEscBound = true;
      document.addEventListener("keydown", function(ev){
        if(ev.key !== "Escape") return;
        // Topmost first. This list has to name every modal in the app --
        // it was written when there were two and the dialogs added since
        // (export, send-for-sign-off, sign-off decision) were never added
        // to it, so Escape silently did nothing on three of the five.
        if(state.exportDialog){ state.exportDialog = null; render(); }
        else if(state.decideDialog){ state.decideDialog = null; render(); }
        else if(state.submitDialog){ state.submitDialog = null; render(); }
        else if(state.viewingHistoryEntryId != null){ state.viewingHistoryEntryId = null; render(); }
        else if(state.viewingEntryId){ state.viewingEntryId = null; render(); }
      });
    }
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

    // Entries list: live text filter -- pure DOM show/hide (same reasoning
    // as the mp-search/ss-search filters above: this fires on every
    // keystroke, and a full re-render mid-keystroke would rebuild the input
    // out from under itself and drop focus). The typed value is written
    // back into state by syncEntriesSearchFromDom() only when some OTHER
    // action on this list is about to render (sort, expand, a menu action).
    document.querySelectorAll("[data-entries-search]").forEach(function(inp){
      inp.oninput = function(){
        var q = inp.value.trim().toLowerCase();
        var list = inp.closest(".card") || document;
        list.querySelectorAll(".entry-card").forEach(function(card){
          var match = !q || (card.getAttribute("data-entries-search-text")||"").indexOf(q)!==-1;
          card.classList.toggle("sp-row-hidden", !match);
        });
      };
    });
    document.querySelectorAll("[data-entries-sort-key]").forEach(function(sel){
      sel.onchange = function(){ setEntriesSortKey(sel.getAttribute("data-entries-sort-key"), sel.value); };
    });
    document.querySelectorAll("[data-entries-sort-dir]").forEach(function(b){
      b.onclick = function(){
        var uiKey = b.getAttribute("data-entries-sort-dir");
        syncEntriesSearchFromDom(uiKey);
        var ui = entriesUI(uiKey);
        ui.sortDir = ui.sortDir==="asc" ? "desc" : "asc";
        render();
      };
    });
    document.querySelectorAll("[data-entry-toggle]").forEach(function(row){
      row.onclick = function(ev){
        if(ev.target && ev.target.closest && ev.target.closest(".entry-menu-wrap")) return; // menu button/items handle their own clicks
        toggleEntryOpen(row.getAttribute("data-entry-toggle"), row.getAttribute("data-entry-id"));
      };
    });
    document.querySelectorAll("[data-entry-menu-btn]").forEach(function(b){
      b.onclick = function(ev){ ev.stopPropagation(); toggleEntryMenu(b.getAttribute("data-entry-menu-btn")); };
    });
    // Close any open row menu on an outside click -- bound once, ever (not
    // per-render, since render() rebuilds the DOM every time and a fresh
    // document-level listener on every wireShellEvents() call would stack
    // indefinitely).
    if(!window.__entlogEntryMenuOutsideBound){
      window.__entlogEntryMenuOutsideBound = true;
      document.addEventListener("click", function(ev){
        if(!state.openEntryMenu) return;
        if(ev.target && ev.target.closest && ev.target.closest(".entry-menu-wrap")) return;
        state.openEntryMenu = null;
        render();
      });
    }

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
    var wizSaveDraftBtn = el("wiz-save-draft"); if(wizSaveDraftBtn) wizSaveDraftBtn.onclick = wizSaveDraft;
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

    /* ---------------- export builder ---------------- */
    var openExp = el("open-export"); if(openExp) openExp.onclick = async function(){
      state.exportDialog = { sel: loadExportSel(), options: null };
      render();
      try{ state.exportDialog.options = await xOptions(); }
      catch(e){ state.exportDialog = null; toast(e.message||"Could not open the export options."); }
      render();
    };
    function expSel(){ return state.exportDialog && state.exportDialog.sel; }
    // Read the two date inputs back before ANY re-render: they are plain
    // DOM, not kept in state, so a render triggered by a checkbox would
    // otherwise wipe a date the user had just typed.
    function syncExpDates(){
      var sel = expSel(); if(!sel) return;
      var f = el("exp-from"), t = el("exp-to");
      if(f) sel.from = f.value || "";
      if(t) sel.to = t.value || "";
    }
    document.querySelectorAll("[data-exp-preset]").forEach(function(b){
      b.onclick = function(){
        syncExpDates();
        var k = b.getAttribute("data-exp-preset"), p = EXPORT_PRESETS[k], sel = expSel();
        sel.types = p.types.slice();
        sel.columns = p.columns.slice();
        render();
      };
    });
    document.querySelectorAll("[data-exp-group]").forEach(function(cb){
      cb.onchange = function(){
        syncExpDates();
        var g = cb.getAttribute("data-exp-group"), v = cb.value, sel = expSel();
        sel[g] = sel[g] || [];
        var i = sel[g].indexOf(v);
        if(cb.checked){ if(i===-1) sel[g].push(v); } else if(i!==-1){ sel[g].splice(i,1); }
        render();
      };
    });
    document.querySelectorAll("[data-exp-col]").forEach(function(cb){
      cb.onchange = function(){
        syncExpDates();
        var sel = expSel(), k = cb.getAttribute("data-exp-col");
        var all = (state.exportDialog.options.columns||[]).map(function(c){ return c.key; });
        var i = sel.columns.indexOf(k);
        if(cb.checked){ if(i===-1) sel.columns.push(k); } else if(i!==-1){ sel.columns.splice(i,1); }
        render();
      };
    });
    document.querySelectorAll("[data-exp-cols]").forEach(function(b){
      b.onclick = function(){
        syncExpDates();
        var sel = expSel(), all = (state.exportDialog.options.columns||[]).map(function(c){ return c.key; });
        sel.columns = b.getAttribute("data-exp-cols")==="all" ? all.slice() : [];
        render();
      };
    });
    document.querySelectorAll("[data-export-cancel]").forEach(function(b){
      b.onclick = function(){ state.exportDialog = null; render(); };
    });
    var expOv = document.querySelector("[data-export-overlay]");
    if(expOv) expOv.onclick = function(ev){ if(ev.target===expOv){ state.exportDialog = null; render(); } };
    var expGo = document.querySelector("[data-export-go]");
    if(expGo) expGo.onclick = function(){
      syncExpDates();
      var d = state.exportDialog;
      saveExportSel(d.sel);
      window.location.href = exportURL(d.sel);
      state.exportDialog = null;
      toast("Building your CSV…");
      render();
    };

    /* ---------------- feedback ---------------- */
    document.querySelectorAll('input[name="fb-kind"]').forEach(function(r){
      r.onchange = function(){ syncFeedbackDraft(); state.feedbackDraft.kind = r.value; render(); };
    });
    document.querySelectorAll('input[name="fb-anon"]').forEach(function(r){
      r.onchange = function(){ syncFeedbackDraft(); state.feedbackDraft.anonymous = (r.value==="anon"); render(); };
    });
    // Subject and message live in the DOM, not in state, so anything that
    // re-renders the page has to lift them out first -- the same rule the
    // entry wizard follows for its free-text fields.
    function syncFeedbackDraft(){
      var s1 = el("fb-subject"), b1 = el("fb-body");
      if(s1) state.feedbackDraft.subject = s1.value;
      if(b1) state.feedbackDraft.body = b1.value;
    }
    var fbSend = el("fb-send"); if(fbSend) fbSend.onclick = once("fb-send", async function(){
      syncFeedbackDraft();
      var d = state.feedbackDraft;
      if(!(d.subject||"").trim()){ toast("Give it a one-line subject."); return; }
      if(!(d.body||"").trim()){ toast("Say what you would like to raise."); return; }
      state.feedbackBusy = true; render();
      try{
        await fbCreate({ kind:d.kind, subject:d.subject, body:d.body, anonymous:d.anonymous });
        var wasAnon = d.anonymous;
        state.feedbackDraft = { kind:"suggestion", subject:"", body:"", anonymous:false };
        state.feedbackBusy = false;
        try{ state.feedbackMine = await fbMine(); }catch(e){}
        if(canReadFeedback()){ try{ state.feedbackInbox = await fbInbox(state.feedbackFilter); }catch(e){} }
        await refreshFeedbackBadge();
        toast(wasAnon ? "Sent anonymously. It carries no link back to you."
                      : "Sent. You can follow it under “What I have raised”.");
        render();
      }catch(e){ state.feedbackBusy=false; toast(e.message||"Could not send that."); render(); }
    });
    document.querySelectorAll("[data-fb-filter]").forEach(function(b){
      b.onclick = async function(){
        syncFeedbackDraft();
        state.feedbackFilter = b.getAttribute("data-fb-filter");
        state.feedbackOpenId = null;
        try{ state.feedbackInbox = await fbInbox(state.feedbackFilter); }catch(e){}
        render();
      };
    });
    document.querySelectorAll("[data-fb-open]").forEach(function(b){
      b.onclick = async function(){
        syncFeedbackDraft();
        var id = parseInt(b.getAttribute("data-fb-open"),10);
        if(state.feedbackOpenId===id){ state.feedbackOpenId=null; render(); return; }
        state.feedbackOpenId = id; render();
        try{
          var d = await fbDetail(id);
          state.feedbackNotes[id] = d.notes || [];
        }catch(e){ state.feedbackNotes[id] = []; toast(e.message||"Could not load that."); }
        render();
      };
    });
    document.querySelectorAll("[data-fb-status]").forEach(function(b){
      b.onclick = async function(){
        syncFeedbackDraft();
        var id = parseInt(b.getAttribute("data-fb-status"),10);
        try{
          await fbSetStatus(id, b.getAttribute("data-fb-value"));
          state.feedbackInbox = await fbInbox(state.feedbackFilter);
          try{ state.feedbackNotes[id] = (await fbDetail(id)).notes || []; }catch(e){}
          await refreshFeedbackBadge();
          render();
        }catch(e){ toast(e.message||"Could not update that."); }
      };
    });
    document.querySelectorAll("[data-fb-note]").forEach(function(b){
      b.onclick = async function(){
        syncFeedbackDraft();
        var id = parseInt(b.getAttribute("data-fb-note"),10);
        var inp = el("fb-note-"+id), note = inp ? inp.value : "";
        if(!note.trim()){ toast("Write the note first."); return; }
        try{
          state.feedbackNotes[id] = await fbAddNote(id, note);
          toast("Note added.");
          render();
        }catch(e){ toast(e.message||"Could not add that."); }
      };
    });

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
        // Pass null, not the swatch's resolved hex: toHexColor() resolved
        // var(--cat-*) against the CURRENT theme, so renaming a site in dark
        // mode used to freeze its dark value in for every light-mode user.
        editCategory(key, inp.value, null);
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
    var restoreProcs = el("restore-procs"); if(restoreProcs) restoreProcs.onclick = once("restore-procs", async function(){
      restoreProcs.disabled = true; restoreProcs.innerHTML = '<span class="spin"></span>Restoring…';
      try{
        var r = await dRestoreProcedureDefaults();
        state.config = r.config;
        var sites = Object.keys(r.restored || {});
        var n = sites.reduce(function(a,k){ return a + r.restored[k]; }, 0);
        toast(n ? "Restored "+n+" procedure"+(n===1?"":"s")+" across "+sites.length+" site"+(sites.length===1?"":"s")+"."
                : "Nothing missing — every default is already in your lists.");
        render();
      }catch(e){
        restoreProcs.disabled = false; restoreProcs.textContent = "Restore default procedure lists";
        toast(e.message || "Could not restore those.");
      }
    });
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
