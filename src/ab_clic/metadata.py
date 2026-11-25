"""Format version-specific CLIC information for Activity Browser."""


def _author_names(people) -> str:
    names = [
        person.get("name", "") if isinstance(person, dict) else person
        for person in people
    ]
    return ", ".join(dict.fromkeys(name for name in names if name))


def catalog_metadata(version: dict) -> dict[str, str]:
    discovery = version.get("discovery_metadata") or {}
    publications = discovery.get("publications") or []
    primary = next(
        (item for item in publications if item.get("relation") == "primary_source"), {}
    )
    authors = (version.get("authors") or []) + [
        contributor
        for contributor in (discovery.get("contributions") or [])
        if "inventory_author" in (contributor.get("roles") or [])
    ]
    background = (version.get("background_context") or {}).get("technosphere") or {}
    quality = version.get("quality_assessment") or {}
    technology = version.get("technology_characterization") or {}
    assessment = version.get("source_inventory_assessment") or {}
    classification = version.get("classification_label") or ""
    code = version.get("classification") or ""
    if code and classification and code != classification:
        classification = f"{classification} ({code})"
    start = discovery.get("data_period_start_year")
    end = discovery.get("data_period_end_year")
    projects = ", ".join(
        dict.fromkeys(
            name
            for project in (discovery.get("projects") or [])
            if (name := project.get("name") or project.get("acronym"))
        )
    )
    fields = {
        "Source publication": primary.get("title"),
        "Publication authors": _author_names(primary.get("authors") or []),
        "Publication year": primary.get("publication_year"),
        "Source citation": primary.get("citation")
        or version.get("original_citation")
        or version.get("source"),
        "Source DOI": primary.get("doi") or version.get("original_doi"),
        "Related publications": "\n".join(
            citation
            for publication in publications
            if publication is not primary
            if (
                citation := (
                    publication.get("citation")
                    or publication.get("title")
                    or publication.get("doi")
                    or publication.get("url")
                )
            )
        ),
        "Inventory authors": _author_names(authors),
        "Projects": projects,
        "Technology readiness level (TRL)": quality.get("technology_readiness_level"),
        "Commercial maturity": technology.get("commercial_maturity_stage_label"),
        "Reference product": version.get("reference_product"),
        "Location": version.get("location"),
        "Unit": version.get("unit"),
        "Classification": classification or code,
        "Keywords": ", ".join(version.get("keywords") or []),
        "License": version.get("selected_license_label"),
        "CLIC version": version.get("semantic_version"),
        "Published on CLIC": (version.get("published_at") or "")[:10],
        "CLIC record": version.get("public_url"),
        "Inventory reference year": discovery.get("inventory_reference_year"),
        "Inventory data period": (
            f"{start}–{end}" if start and end and start != end else start or end
        ),
        "Source background": " ".join(
            str(background[field])
            for field in ("family", "version", "system_model")
            if background.get(field)
        ),
        "Modelling approach": (discovery.get("modelling_approach") or "")
        .replace("_", " ")
        .capitalize(),
        "Inventory changes relative to source": assessment.get("status_label"),
        "Technology": discovery.get("technology_description"),
        "System boundary": discovery.get("system_boundary"),
        "Intended application": discovery.get("intended_application"),
        "Use limitations": discovery.get("use_limitations"),
    }
    return {
        label: str(value).strip()
        for label, value in fields.items()
        if value is not None and str(value).strip()
    }


def inventory_comment(version: dict, existing: str = "") -> str:
    description = (version.get("description") or "").strip()
    paragraphs = [existing] if existing.strip() else []
    if description and description != existing.strip():
        paragraphs.append(description)
    fields = catalog_metadata(version)
    if fields:
        paragraphs.append(
            "CLIC metadata\n"
            + "\n".join(f"{label} — {value}" for label, value in fields.items())
        )
    return "\n\n".join(paragraphs)
