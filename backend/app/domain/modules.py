from __future__ import annotations

from app.domain.enums import ProgrammeCode
from app.domain.indicator_catalog import EPI_COVERAGE_SPECS

MODULE_PROGRAMME = {
    "anc": ProgrammeCode.MNCH.value,
    "intrapartum": ProgrammeCode.MNCH.value,
    "immunization": ProgrammeCode.EPI.value,
    "mpdsr": ProgrammeCode.MPDSR.value,
}

MODULE_INDICATORS = {
    "anc": [
        "ANC1_COVERAGE",
        "ANC1_FIRST_TRIMESTER",
        "ANC4_COVERAGE",
        "ANC8_COVERAGE",
        "IPT3_COVERAGE",
        "HB_TESTING",
        "IFA_COVERAGE",
        "OBSTETRIC_ULTRASOUND",
        "TEENAGE_PREGNANCY",
    ],
    "intrapartum": [
        "INSTITUTIONAL_DELIVERY",
        "CAESAREAN_SECTION",
        "KMC",
        "SUCCESSFUL_RESUSCITATION",
        "PMR",
        "FRESH_STILLBIRTH_RATE",
        "MMR",
    ],
    "immunization": [row[0] for row in EPI_COVERAGE_SPECS]
    + [
        "PENTA_DROPOUT",
        "MV1_MV4_DROPOUT",
    ],
    "mpdsr": [
        "PERINATAL_REPORTED_DEATHS",
        "PERINATAL_NOTIFIED_COUNT",
        "PERINATAL_NOTIFICATION_COVERAGE",
        "PERINATAL_TIMELY_NOTIFICATION",
        "PERINATAL_REVIEWED_COUNT",
        "PERINATAL_REVIEW_COVERAGE",
        "PERINATAL_TIMELY_REVIEW",
        "MATERNAL_REPORTED_DEATHS",
        "MATERNAL_NOTIFIED_COUNT",
        "MATERNAL_NOTIFICATION_COVERAGE",
        "MATERNAL_TIMELY_NOTIFICATION",
        "MATERNAL_REVIEWED_COUNT",
        "MATERNAL_REVIEW_COVERAGE",
        "MATERNAL_TIMELY_REVIEW",
    ],
}
