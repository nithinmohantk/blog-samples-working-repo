# EHDS Provisional Agreement: What EHR Systems Must Build Into the Access Path

*Saturday 23 March 2024. Slug `ehds-provisional-agreement-what-ehr-systems-must-build`*

**Excerpt:** The March 2024 EHDS deal makes EHR systems a regulated product with a logging component. Access logs per Annex II, restrictions that leave no trace, emergency access and the patient's access report, built on FHIR R4 and tested on HAPI FHIR.

In the early hours of Friday 15 March 2024, the Council and the European Parliament reached a provisional agreement on the regulation for a European Health Data Space. The Council published the compromise text on 18 March as document 7553/24. It still needs formal adoption by both institutions, and some passages carry drafting marks, but the obligations for anyone who builds or buys an electronic health record system are now clear enough to plan against.

Most of the coverage has been about secondary use: research access, health data access bodies and the new opt-out. This article is about primary use, the care side, and in particular the access path of an EHR system: who may see which data, how a patient's restrictions are applied, what is logged, and what the patient is told. These are the parts a vendor will build first, because they touch every screen and every API call. The sample code implements them on FHIR R4 and runs against a HAPI FHIR server.

## What the agreement asks of an EHR system

Chapter III treats an EHR system as a regulated product. It must meet the essential requirements in Annex II, carry an EU declaration of conformity and a CE marking, and be registered in a public EU database before it is placed on the market. Two software parts are defined in Article 2: a European interoperability component that provides and receives personal electronic health data, and a European logging component that provides logging information on health professionals' access to that data. Together they are the harmonised components that the conformity rules apply to.

| Provision | What it means for the product |
| :--- | :--- |
| Article 5(1) | Six priority categories: patient summaries, ePrescriptions, eDispensations, imaging studies and reports, test results and reports, discharge reports |
| Annex II, section 2 | Make data available in the European health record exchange format, capture it at a granularity that allows that export, and do not obstruct export when a customer replaces the system |
| Annex II, point 3.2 | Reliable identification and authentication of health professionals |
| Annex II, point 3.4 | Log every access: provider, individual, data categories, date and time, origin of the data |
| Annex II, point 3.6 | Tools to review and analyse the logs, or a connection to external software that does |
| Article 17 | Technical documentation, EU declaration of conformity and CE marking; keep both documents for 10 years |
| Article 26a | Test in the European or national digital testing environment before release; positive results presume conformity for what was tested |
| Article 32 | Register in the EU database for EHR systems, including the test results |

The Council's note on the deal describes this as a self-certification scheme supported by a digital testing environment. That is lighter than medical device certification, but it moves the evidence burden onto the vendor: the technical documentation has to show how each Annex II requirement is met, and Article 16 forbids claims about interoperability or security that the product does not support.

![Diagram of an EHR access path under the EHDS provisional agreement: a health professional's request passes an access gateway that applies Article 8e restrictions and Article 7a(3) emergency access, reads the FHIR record, and writes an AuditEvent to a logging component that feeds the patient's Article 8f access report](img1.jpg)
*The access path the sample implements, with the article behind each step.*

## Mapping data to the priority categories

Restrictions, logs and the patient's report all speak in terms of the Article 5 categories, so the system needs a reliable way to place each record in one. The provisional agreement does not define that mapping. It will come with the exchange format in implementing acts, due within two years of entry into force. Until then a working mapping, kept in one function so it can change, is the practical choice:

```python
def category_of(resource: dict) -> str | None:
    """The Article 5 category of one FHIR R4 resource, or None if it is outside the priority categories."""
    rtype = resource.get("resourceType")
    if rtype == "MedicationRequest":
        return EPRESCRIPTION
    if rtype == "MedicationDispense":
        return EDISPENSATION
    if rtype == "ImagingStudy":
        return IMAGING
    if rtype in ("Composition", "DocumentReference"):
        for code in _codes(resource.get("type"), LOINC):
            if code in DOC_TYPES:
                return DOC_TYPES[code]
        return None
    if rtype == "DiagnosticReport":
        cats = _codes(resource.get("category"), V2_0074)
        return IMAGING if cats & RADIOLOGY else TEST_RESULTS
    if rtype == "Observation":
        cats = _codes(resource.get("category"), OBS_CATEGORY)
        if "imaging" in cats:
            return IMAGING
        return TEST_RESULTS if cats & {"laboratory", "procedure"} else None
    return None
```

Two cases need care. A DiagnosticReport is a test result or an imaging report depending on its category, so the radiology codes decide. And documents are classified by their LOINC type, which works for structured patient summaries and discharge summaries but not for a scanned letter filed with a generic type. Anything the function cannot place is logged as `other`, which is visible in the patient's report rather than silently dropped.

## The log record

Annex II point 3.4 lists five things to log for each access or group of accesses. FHIR R4 already has a resource for this, AuditEvent, and every item has a natural home in it: the organisation and the individual are agents, the categories and the origin are details on each data entity, and the time is `recorded`.

```python
def access_event(requester: Requester, patient: str, returned: list[dict], *, interaction: str,
                 emergency: bool = False, observer: str = "Device/ehr-system",
                 when: datetime | None = None) -> dict:
    """The AuditEvent for one request. `returned` is what the user actually saw, after any restriction."""
    recorded = (when or datetime.now(timezone.utc)).isoformat(timespec="milliseconds")
    entities = [{"what": {"reference": patient},
                 "type": {"system": ENTITY_TYPE, "code": "1", "display": "Person"},
                 "role": {"system": OBJECT_ROLE, "code": "1", "display": "Patient"}}]
    for resource in returned:
        category = category_of(resource)
        entities.append({
            "what": {"reference": f"{resource['resourceType']}/{resource['id']}"},
            "type": {"system": ENTITY_TYPE, "code": "2", "display": "System Object"},
            "role": {"system": OBJECT_ROLE, "code": "4", "display": "Domain Resource"},
            "detail": [{"type": CATEGORY_DETAIL, "valueString": category or "other"},
                       {"type": ORIGIN_DETAIL, "valueString": origin_of(resource)}],
        })
    reason = ("ETREAT", "Emergency Treatment") if emergency else ("TREAT", "treatment")
    return {
        "resourceType": "AuditEvent",
        "type": {"system": DCM, "code": "110110", "display": "Patient Record"},
        "subtype": [{"system": RESTFUL, "code": interaction}],
        "action": "R" if interaction == "read" else "E",
        "recorded": recorded,
        "outcome": "0",
        "purposeOfEvent": [{"coding": [{"system": ACT_REASON, "code": reason[0], "display": reason[1]}]}],
        "agent": [
            {"who": {"reference": requester.practitioner, "display": requester.practitioner_name},
             "requestor": True},
            {"who": {"reference": requester.organization, "display": requester.organization_name},
             "requestor": False},
        ],
        "source": {"observer": {"reference": observer}},
        "entity": entities,
    }
```

Two design choices matter more than the field mapping. The event lists what the user actually saw after restrictions were applied, not what the query matched; a log that records hidden data as accessed would show the patient accesses that never happened. And the origin is recorded per item, because a patient summary held by a GP may contain results from a laboratory and a hospital, and Annex II asks for the origin of the data, not the location of the copy. This is part of the event that the CI run stored on the HAPI server for an emergency access:

```json
  "purposeOfEvent": [
    {
      "coding": [
        {
          "system": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
          "code": "ETREAT",
          "display": "Emergency Treatment"
        }
      ]
    }
  ],
  "agent": [
    {
      "who": {
        "reference": "Practitioner/dr-ed-a",
        "display": "Dr Emergency-A"
      },
      "requestor": true
    },
    {
      "who": {
        "reference": "Organization/hospital-a",
        "display": "Hospital A"
      },
      "requestor": false
    }
  ]
```

Each data item carries its category and origin as details:

```json
    {
      "what": {
        "reference": "Observation/hba1c-1"
      },
      "type": {
        "system": "http://terminology.hl7.org/CodeSystem/audit-entity-type",
        "code": "2",
        "display": "System Object"
      },
      "role": {
        "system": "http://terminology.hl7.org/CodeSystem/object-role",
        "code": "4",
        "display": "Domain Resource"
      },
      "detail": [
        {
          "type": "ehds-category",
          "valueString": "test-results"
        },
        {
          "type": "ehds-origin",
          "valueString": "Organization/lab-d"
        }
      ]
    }
```

The first CI run found a useful property of HAPI here. The server enforces referential integrity, so an AuditEvent whose `source.observer` points at a Device that does not exist is rejected with HTTP 400. Because the gateway writes the log before it returns data, the request failed rather than returning data without a log. That is the behaviour to want, and it is worth testing deliberately: one of the unit tests makes the log store fail and checks that nothing is returned.

## Restrictions that leave no trace

Article 8e gives a person the right to restrict health professionals' and providers' access to all or part of their data, after being told that this may affect their care. It also says the fact that a restriction exists shall not be visible to healthcare providers, and Article 7a(3) adds that providers are not informed of the restricted content. Filtering records is easy. Filtering them without leaving a trace takes more thought:

```python
def visible(resources: list[dict], restriction: Restriction | None, organization: str,
            *, emergency: bool = False) -> list[dict]:
    if restriction is None or emergency or organization in restriction.except_providers:
        return list(resources)
    return [r for r in resources if category_of(r) not in restriction.categories]


def searchset(resources: list[dict]) -> dict:
    """A Bundle built from the filtered list only. Passing on the server's total would count hidden items."""
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"fullUrl": f"{r['resourceType']}/{r['id']}", "resource": r,
                       "search": {"mode": "match"}} for r in resources]}
```

The CI scenario shows why `searchset` builds its own Bundle. The patient restricts test results for everyone except their GP, and a hospital doctor searches for observations:

```text
== 2. The patient restricts test results for everyone except their GP (Article 8e)
Hospital A, Observation: ['bp-1'] total 1   (the server's own total: 3)
Hospital A, DiagnosticReport: ['xray-report-1'] total 1
GP Practice B, Observation: ['hba1c-1', 'creat-1', 'bp-1'] total 3
```

The server counted three matching observations. A gateway that filtered the entries but passed on the server's total would tell the hospital that two results exist and are being withheld, which is exactly what Article 8e forbids. The count is the obvious leak; there are others that a test suite should cover:

- **References from visible records.** A DiagnosticReport that is shown may reference Observations that are hidden. Following the reference returns nothing, which is itself a signal. Either hide the referring record too or strip the references.
- **Data embedded in documents.** A patient summary can contain recent results in its narrative. Category filtering at resource level does not remove them; that needs section-level handling or a regenerated summary.
- **Includes and paging.** `_include`, `_revinclude` and page sizes computed before filtering all reveal hidden items. The sample avoids them by reading every page and building the result itself.
- **Error messages.** A read of a hidden record by ID must look the same as a read of a record that does not exist.

The gateway puts the steps together and keeps the order that matters: filter, log what is shown, then return.

```python
    def search(self, requester: Requester, patient: str, rtype: str, params: dict | None = None,
               *, emergency: bool = False) -> dict:
        query = {"patient": patient, "_count": 100, **(params or {})}
        found, _server_total = self.fhir.search_all(rtype, query)
        shown = visible(found, self.restrictions.get(patient), requester.organization, emergency=emergency)
        # Log before returning: an access that cannot be logged is not served.
        self.fhir.create(access_event(requester, patient, shown, interaction="search-type",
                                      emergency=emergency, when=self.clock()))
        return searchset(shown)
```

## Emergency access

Article 7a(3) lets a provider reach restricted data where access is necessary to protect the vital interests of the person, and requires that access to be logged in a clear format the person can easily read. In the sample this is an explicit flag on the request, recorded as `purposeOfEvent` ETREAT:

```text
== 3. Emergency access to restricted data (Article 7a(3))
Hospital A emergency department, Observation: ['hba1c-1', 'creat-1', 'bp-1'] total 3
```

The flag should not be a checkbox anyone can tick. In production it belongs behind a separate permission, a reason the clinician enters, and a review of every use, the usual break-glass controls. There is also a FHIR R4 gap to plan for. The server's CapabilityStatement lists the AuditEvent search parameters it supports, and none of them covers `purposeOfEvent`:

```text
AuditEvent search parameters in the CapabilityStatement: _content, _filter, _has, _id, _lastUpdated, _profile, _security, _source, _tag, _text, action, address, agent, agent-name, agent-role, altid, date, entity, entity-name, entity-role, entity-type, outcome, patient, policy, site, source, subtype, type
```

The CI run confirmed that a search on `purpose` is rejected as an unknown parameter. A system that needs to list emergency accesses, for a privacy officer's review or for notifications, must either read every event for the patient and filter, as the sample's report does, or define a custom SearchParameter. The `entity`, `patient`, `agent` and `date` searches all worked as expected and returned the six events the scenario wrote.

## The patient's access report

Article 8f gives the person the right to see who accessed their data, including through automatic notifications. The information is provided without delay and free of charge, through the electronic health data access services that Article 8g requires Member States to set up, and stays available for at least three years after each access. It must cover at least the healthcare provider or other individuals who accessed the data, the date and time, and the data accessed. This is the report the sample builds from the events on the server:

```text
When (UTC)               Provider                   Who                Data
2024-03-21 02:15:07      Hospital A                 Dr Emergency-A     other, test-results  EMERGENCY ACCESS
2024-03-20 18:40:21      GP Practice B              Dr GP-B            other, test-results
2024-03-20 18:40:14      Hospital A                 Dr Hospital-A      imaging
2024-03-20 18:40:07      Hospital A                 Dr Hospital-A      other
2024-03-20 09:10:14      Hospital A                 Dr Hospital-A      other, test-results
2024-03-20 09:10:07      GP Practice B              Dr GP-B            patient-summary
```

Two details from the text are configuration, not code. Member States may restrict the right in exceptional circumstances, for example where naming a professional would endanger them, so whether the individual's name appears is a setting; the sample renders the same report with the column withheld. And the three years are a minimum. National retention rules for clinical records and logs are often longer, so the deletion check only says when deletion becomes permissible under this rule:

```python
def keep_until(recorded: datetime, years: int = 3) -> datetime:
    """'At least three years after each data access'. An access on 29 February is kept until 1 March."""
    try:
        return recorded.replace(year=recorded.year + years)
    except ValueError:
        return recorded.replace(year=recorded.year + years, month=3, day=1)
```

The report also exposes the quality of the category mapping. In the run above, the hospital's first search shows `other` next to test results: that is the blood pressure reading, a vital sign outside the priority categories. A patient will ask what `other` means, so the final product needs readable names and probably the item names as well.

## Opt-out and access services

Article 8h lets Member States give people a full, reversible opt-out from access to their data through the EHDS infrastructure, with access still possible to protect vital interests. It is optional, so an EHR system sold in several countries will meet both regimes. The same mechanism as restrictions handles it: an opt-out is a restriction of every category for every provider outside the person's own care setting, with the emergency path unchanged. Building restrictions as data rather than as code, as the sample does, keeps national variants to configuration.

Article 8g also covers proxies, people authorised to act for someone else, such as a parent or carer. Restrictions and access reports therefore need to know who set them and on whose behalf, which is another reason to store them as durable records, for example as FHIR Consent resources, rather than as flags on the patient.

## When it applies

Article 72 counts everything from entry into force, which is 20 days after publication in the Official Journal. On 23 March 2024 that date is not known, but the sequence is:

![Timeline of EHDS application periods counted from entry into force: general application after 2 years, implementing acts within 2 years, patient summaries, ePrescriptions and dispensations after 4 years, secondary use after 4 years, imaging, test results and discharge reports after 6 years](img2.jpg)
*Application periods from Article 72 of the provisional agreement.*

The four-year group, patient summaries, ePrescriptions and dispensations, is where cross-border exchange already runs through MyHealth@EU, so the categories with existing national services come first. Imaging, test results and discharge reports follow two years later. The Chapter II provisions, which include the restriction, logging and access-report rights in this article, are tied to these category dates rather than to the two-year general date, so the access path has to be ready for the first three categories at four years.

## What to do now

- **Map your data to the six categories.** Find out how much of the record a function like `category_of` can place today, and what is left as `other`.
- **Put one access path in front of the record.** Restrictions and logging only work if every screen, API and export goes through them, including batch interfaces and support tools.
- **Log what was shown, with its origin.** Check the existing audit trail against the five items in Annex II point 3.4; origin of the data is the one most systems lack.
- **Test for traces of restrictions.** Counts, references, includes, documents and error messages.
- **Design break-glass access.** Separate permission, recorded reason, review, and a log entry the patient can read.
- **Plan the technical documentation.** Each Annex II requirement will need evidence, and the testing environment results go into the EU database.
- **Watch the implementing acts.** The exchange format, the logging format in Annex II and the testing specifications all arrive within two years.

> **PROVISIONAL TEXT**  
> Article numbers and wording here are from the provisional agreement text of 18 March 2024. The text still has to be formally adopted, and numbering usually changes in the final version. Check the adopted regulation before quoting articles in contracts or tenders.

## Decision framework

| Situation | Recommendation |
| :--- | :--- |
| EHR product sold in the EU | Plan for Chapter III conformity: Annex II evidence, declaration, CE marking and registration |
| Existing audit trail logs requests, not data shown | Change it to log the filtered result, with categories and origin per item |
| Restrictions implemented as UI hiding | Move them into the data access path so APIs and exports apply them too |
| FHIR R4 server as the audit store | Use AuditEvent, write it before returning data, and add a custom SearchParameter for purposeOfEvent if you need to search it |
| Selling in several Member States | Treat opt-out, proxy rules and name disclosure in access reports as configuration |
| In-house system at a hospital | Check whether it falls under Article 13b(2), which has the longer six-year period |

> **HOW THIS WAS CHECKED**  
> The sample ran in GitHub Actions ([run](https://github.com/nithinmohantk/blog-samples-working-repo/actions/runs/44390722475)) on Python 3.12 with pytest 8.1.1 (packages as of 22 March 2024) against the `hapiproject/hapi:v7.0.3` image, tagged on 7 March 2024, which reports HAPI FHIR Server 7.0.2. The patient, organisations and clinicians are synthetic. The 14 unit tests passed, and the scenario output above is copied from that run. Article numbers and quotations come from the Council's provisional agreement text, document 7553/24 of 18 March 2024. The category mapping is an assumption, because the exchange format had not been defined. No legal advice is implied.

## Key takeaways

- The provisional agreement of 15 March 2024 makes EHR systems a regulated product with two harmonised components: interoperability and logging.
- Annex II point 3.4 asks for five items per access; the origin of the data is the one most audit trails lack.
- Article 8e restrictions must leave no trace, so totals, references and errors have to be rebuilt after filtering.
- Emergency access to restricted data is allowed and must be logged in a form the patient can read; FHIR R4 cannot search AuditEvent by purpose without a custom parameter.
- Obligations apply by category, four years after entry into force for summaries and prescriptions and six years for the rest.

If you are working through the Annex II requirements for your own product, let me know in the comments below which ones are proving hardest.

> **GET THE CODE**  
> [https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/ehds-access-logging](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/ehds-access-logging)

## Glossary

- **EHDS**: European Health Data Space: the EU regulation on primary and secondary use of electronic health data.
- **Provisional agreement**: The text agreed by Council and Parliament negotiators, before formal adoption by both.
- **Primary use**: Use of health data for the care of the person it describes.
- **Secondary use**: Use of health data for research, policy, statistics and similar purposes.
- **EHR system**: A system for storing and sharing electronic health records; Article 2 gives the full definition.
- **Harmonised components**: The European interoperability component and the European logging component of an EHR system.
- **Priority categories**: The six data categories in Article 5(1) that must be exchangeable first.
- **European health record exchange format**: The common format for the priority categories, to be specified in implementing acts.
- **AuditEvent**: The FHIR resource for recording security and access events.
- **ETREAT**: HL7 v3 ActReason code for emergency treatment, used here to mark vital-interest access.
- **Break-glass access**: An emergency override of normal access controls, with extra logging and review.
- **CapabilityStatement**: A FHIR server's description of what it supports, including search parameters.

## References & Further Reading

- [European Health Data Space: Council and Parliament strike deal](https://www.consilium.europa.eu/en/press/press-releases/2024/03/15/european-health-data-space-council-and-parliament-strike-provisional-deal/): Council press release, 15 March 2024
- [Provisional agreement text](https://www.consilium.europa.eu/media/70909/st07553-en24.pdf): Council document 7553/24, 18 March 2024
- [EU Health Data Space to support patients and research](https://www.europarl.europa.eu/news/en/press-room/20240304IPR18765/eu-health-data-space-to-support-patients-and-research): European Parliament press release
- [European Health Data Space](https://health.ec.europa.eu/ehealth-digital-health-and-care/european-health-data-space_en): European Commission overview
- [FHIR R4 AuditEvent](https://hl7.org/fhir/R4/auditevent.html): Resource definition and search parameters
- [HAPI FHIR JPA Server Starter](https://github.com/hapifhir/hapi-fhir-jpaserver-starter): The server image used in the tests
- [Sample code for this article](https://github.com/nithinmohantk/blog-samples-working-repo/tree/main/ehds-access-logging): Categories, AuditEvent builder, restriction filter, gateway, patient report and tests
