"""Bilingual templates for the rationale and warning text components generate.

``lang`` flows from each pipeline's top-level ``lang`` param (``"pt-BR"`` by default, or ``"en-US"``) to every
component's own ``lang`` param, and from there into the functions here. This covers only natural-language text a
lawyer reads (rationale paragraphs, warnings, the rebuttal writer's language directive) — structured fields
(``severity``, ``strength``, ``confidence``, rejection reason codes like ``quote_not_found``) stay the stable
English identifiers other code and tests match on; only the prose *around* them is translated.
"""

from __future__ import annotations

from typing import Literal

Lang = Literal["pt-BR", "en-US"]

_SEV_PT = {"high": "alta", "medium": "média"}
_PHASE_PT = {"inquerito": "na fase de inquérito", "judicial": "na fase judicial", "pericial": "na fase pericial"}


def _join(items: list[str]) -> str:
    return ", ".join(items)


# ----------------------------------------------------------------------------- eproc_split
def no_pdfs_found(lang: Lang, root: str) -> str:
    if lang == "pt-BR":
        return f"nenhum PDF encontrado em {root}"
    return f"no PDF files found in {root}"


def unclassified_documents(lang: Lang, n: int) -> str:
    if lang == "pt-BR":
        return f"{n} documento(s) não reconhecido(s) pelos padrões conhecidos; marcados como OUTRO (extenda DOC_TYPE_PATTERNS se necessário)"
    return f"{n} document(s) matched none of the known patterns; tagged OUTRO (extend DOC_TYPE_PATTERNS if needed)"


# ----------------------------------------------------------------------------- process_ingest
def too_many_documents(lang: Lang, n_found: int, max_docs: int) -> str:
    if lang == "pt-BR":
        return f"{n_found} documentos encontrados; apenas os primeiros {max_docs} foram lidos"
    return f"{n_found} documents found; only the first {max_docs} were read"


def phase_not_recognised(lang: Lang, doc_id: str) -> str:
    if lang == "pt-BR":
        return f"{doc_id}: fase não reconhecida; defina-a em params.phases"
    return f"{doc_id}: phase not recognised; set it in params.phases"


def pypdf_missing(lang: Lang, filename: str) -> str:
    if lang == "pt-BR":
        return f"{filename}: instale o pypdf para ler PDFs (pip install pypdf); ignorado"
    return f"{filename}: install pypdf to read PDFs (pip install pypdf); skipped"


def no_text_layer(lang: Lang, filename: str) -> str:
    if lang == "pt-BR":
        return f"{filename}: sem camada de texto (digitalizado?); faça OCR antes; ignorado"
    return f"{filename}: no text layer (scanned?); run OCR first; skipped"


# ----------------------------------------------------------------------------- crime_classify
def no_charges_found(lang: Lang) -> str:
    if lang == "pt-BR":
        return "nenhum artigo de acusação foi encontrado; informe params.articles ou verifique a camada de texto da denúncia"
    return "no charged article found; pass params.articles or check the denuncia text layer"


def unknown_charge(lang: Lang, key: str) -> str:
    if lang == "pt-BR":
        return f"{key} não está na ontologia; adicione-o a data/crimes.yaml (ou a params.crimes_path)"
    return f"{key} is not in the ontology; add it to data/crimes.yaml (or params.crimes_path)"


def charge_rationale(lang: Lang, key: str, locs: list[str]) -> str:
    if lang == "pt-BR":
        where = f"citado em {_join(locs[:3])}" if locs else "informado manualmente em params.articles"
        return (
            f"{key} foi considerado uma acusação porque está {where}. Cada elemento listado é algo que a acusação "
            "deve provar de forma independente, de modo que a análise busca evidência judicial própria para cada "
            "elemento, em vez de julgar a acusação como um todo."
        )
    where = f"cited at {_join(locs[:3])}" if locs else "given manually in params.articles"
    return (
        f"{key} was taken as a charge because it is {where}. Each listed element is something the accusation must "
        "prove on its own, so the analysis looks for independent judicial evidence of every element instead of "
        "judging the charge as a whole."
    )


# ----------------------------------------------------------------------------- evidence_segment
def evidence_left_out(lang: Lang, n: int, left: list[str]) -> str:
    if lang == "pt-BR":
        return f"{n} documento(s) não couberam em max_chars e foram deixados de fora: {left}"
    return f"{n} documents did not fit max_chars and were left out: {left}"


# ----------------------------------------------------------------------------- claim_verify
def claims_citing_loosely(lang: Lang, n_rejected: int, n_total: int) -> str:
    if lang == "pt-BR":
        return (
            f"{n_rejected} de {n_total} alegações falharam na verificação: o extrator está citando de forma imprecisa"
        )
    return f"{n_rejected} of {n_total} claims failed verification: the extractor is citing loosely"


# ----------------------------------------------------------------------------- consistency_check
def retraction_rationale(
    lang: Lang,
    speaker: str,
    slot: str,
    about: str,
    val_x: str,
    phase_x: str,
    loc_x: str,
    val_y: str,
    phase_y: str,
    loc_y: str,
) -> str:
    if lang == "pt-BR":
        px, py = _PHASE_PT.get(phase_x, phase_x), _PHASE_PT.get(phase_y, phase_y)
        return (
            f"{speaker} descreveu '{slot}' de '{about}' como '{val_x}' {px} ({loc_x}) e como '{val_y}' {py} "
            f"({loc_y}). Uma mudança de versão pela mesma pessoa entre as fases fragiliza ambas as declarações e "
            "é o primeiro ponto a explorar em contraditório ou em alegações finais."
        )
    return (
        f"{speaker} described '{slot}' of '{about}' as '{val_x}' in the {phase_x} phase ({loc_x}) and as '{val_y}' "
        f"in the {phase_y} phase ({loc_y}). A change of version by the same person between phases weakens both "
        "statements and is the first thing to explore in cross-examination or closing."
    )


def slot_conflict_rationale(
    lang: Lang,
    speaker_x: str,
    role_x: str,
    loc_x: str,
    val_x: str,
    speaker_y: str,
    role_y: str,
    loc_y: str,
    val_y: str,
    slot: str,
    about: str,
    severity: str,
) -> str:
    high = severity == "high"
    if lang == "pt-BR":
        sev = _SEV_PT.get(severity, severity)
        why = "diz respeito à identificação do autor." if high else "afeta a credibilidade."
        return (
            f"{speaker_x} ({role_x}, {loc_x}) afirma que '{slot}' era '{val_x}', enquanto {speaker_y} ({role_y}, "
            f"{loc_y}) afirma '{val_y}'. As duas versões não podem ser verdadeiras sobre '{about}'; a regra marca "
            f"isso como {sev} porque {why}"
        )
    why = "it bears on identifying the agent." if high else "it affects credibility."
    return (
        f"{speaker_x} ({role_x}, {loc_x}) says '{slot}' was '{val_x}' while {speaker_y} ({role_y}, {loc_y}) says "
        f"'{val_y}'. Both cannot be true about '{about}'; the rule flags it as {severity} because {why}"
    )


def missing_element_rationale(lang: Lang, label: str, charge_id: str, proof_hint: str) -> str:
    if lang == "pt-BR":
        return (
            f"Nenhuma alegação verificada nos autos sustenta '{label}' de {charge_id}. O elemento normalmente "
            f"seria provado por meio de {proof_hint}; sem ele, a acusação apresenta uma lacuna que a defesa pode "
            "apontar diretamente."
        )
    return (
        f"No verified claim in the record supports '{label}' of {charge_id}. The element would typically be "
        f"proved by {proof_hint}; without it the accusation has a gap that the defence can point to directly."
    )


def inquiry_only_rationale(lang: Lang, label: str, locs: list[str]) -> str:
    if lang == "pt-BR":
        return (
            f"'{label}' é sustentado apenas por material da fase de inquérito ({_join(locs[:3])}). Prova não "
            "repetida sob o contraditório tem menor peso, de modo que este elemento foi direcionado à busca de "
            "jurisprudência sobre prova produzida apenas no inquérito."
        )
    return (
        f"'{label}' is supported only by inquiry-phase material ({_join(locs[:3])}). Evidence not repeated under "
        "adversarial proceedings carries less weight, so this element was routed to the authority search for the "
        "rule on inquiry-only evidence."
    )


def single_source_rationale(lang: Lang, label: str, speaker: str, role: str, locs: list[str]) -> str:
    if lang == "pt-BR":
        return (
            f"'{label}' depende de um único depoente, {speaker} ({role}), em {_join(locs[:3])}. Sem corroboração "
            "de outra testemunha ou documento, o elemento depende inteiramente da credibilidade dessa pessoa."
        )
    return (
        f"'{label}' rests on a single speaker, {speaker} ({role}), at {_join(locs[:3])}. With no corroboration "
        "from another witness or a document, the element depends entirely on that person's credibility."
    )


def outlier_speaker_rationale(lang: Lang, speaker: str, count: int, mean: float) -> str:
    if lang == "pt-BR":
        return (
            f"{speaker} está envolvido(a) em {count} conflitos, bem acima dos demais depoentes (média {mean:.1f}). "
            "Um valor estatisticamente atípico não é prova de falsidade, mas indica o depoimento cuja consistência "
            "merece leitura mais atenta."
        )
    return (
        f"{speaker} is involved in {count} conflicts, well above the other speakers (mean {mean:.1f}). A "
        "statistical outlier is not proof of falsehood, but it marks the testimony whose consistency deserves the "
        "closest reading."
    )


# ----------------------------------------------------------------------------- argument_map
def accusation_point_rationale(lang: Lang, strong: bool, n_speakers: int, threshold: int, high_rules: list[str]) -> str:
    rules_joined = _join(high_rules)
    if lang == "pt-BR":
        strength = "forte" if strong else "fraco"
        tail = (
            "Atacá-lo exige nova prova, e não apenas inconsistência nos autos."
            if strong
            else "É um alvo de refutação para a defesa."
        )
        return (
            f"Classificado como {strength} porque conta com evidência judicial ou pericial de {n_speakers} "
            f"depoente(s) distinto(s) (limite {threshold}) e {len(high_rules)} anomalia(s) de alta severidade: "
            f"{rules_joined or 'nenhuma'}. {tail}"
        )
    strength = "strong" if strong else "weak"
    tail = (
        "Attacking it needs new evidence rather than inconsistency in the record."
        if strong
        else "It is a refutation target for the defence."
    )
    return (
        f"Marked {strength} because it has judicial or expert evidence from {n_speakers} distinct speaker(s) "
        f"(threshold {threshold}) and {len(high_rules)} high-severity anomaly(ies): {rules_joined or 'none'}. {tail}"
    )


def defence_point_from_anomaly_rationale(
    lang: Lang, anomaly_id: str, rule: str, severity: str, anomaly_rationale: str
) -> str:
    if lang == "pt-BR":
        return f"Derivado da anomalia {anomaly_id} ({rule}, {severity}). {anomaly_rationale}"
    return f"Derived from anomaly {anomaly_id} ({rule}, {severity}). {anomaly_rationale}"


def defence_point_from_claim_rationale(lang: Lang, speaker: str, loc: str, n_corroborating: int) -> str:
    if lang == "pt-BR":
        tail = (
            f"corroborada por {n_corroborating} outro(s) depoente(s), por isso é mantida como forte."
            if n_corroborating
            else "sem corroboração de mais ninguém, por isso é mantida como fraca e não deve sustentar a defesa "
            "isoladamente."
        )
        return f"Versão da defesa apresentada por {speaker} em {loc}; está {tail}"
    tail = (
        f"corroborated by {n_corroborating} other speaker(s), so it is kept as strong."
        if n_corroborating
        else "not corroborated by anyone else, so it is kept as weak and should not carry the defence alone."
    )
    return f"Defence version given by {speaker} at {loc}; it is {tail}"


# ----------------------------------------------------------------------------- authority_select
def authority_rationale(
    lang: Lang, ref: str, point_id: str, words: list[str], score: float, confidence: str, binding: bool
) -> str:
    words_joined = _join(sorted(words)[:5])
    if lang == "pt-BR":
        conf = _SEV_PT.get(confidence, confidence)
        tail = "vinculante." if binding else "persuasiva, não vinculante."
        return f"{ref} corresponde ao ponto {point_id} em {words_joined} (BM25 {score:.2f}); confiança {conf} porque é {tail}"
    tail = "binding." if binding else "persuasive, not binding."
    return f"{ref} matched point {point_id} on {words_joined} (BM25 {score:.2f}); confidence {confidence} because it is {tail}"


def needs_research_warning(lang: Lang, needs: list[str]) -> str:
    if lang == "pt-BR":
        return f"{len(needs)} ponto(s) sem autoridade selecionada e que precisam de pesquisa humana: {needs[:6]}"
    return f"{len(needs)} points have no authority and need human research: {needs[:6]}"


# ----------------------------------------------------------------------------- dossier_build
def writer_language_directive(lang: Lang) -> str:
    """Instruction appended to the dossier's ``rules`` so the writer defaults to ``lang`` (not translated itself)."""
    if lang == "pt-BR":
        return "Escreva weakness, counterargument e rationale em português (pt-BR)."
    return "Write weakness, counterargument and rationale in English (en-US)."


# ----------------------------------------------------------------------------- rebuttal_check
def rebuttal_rejected_warning(lang: Lang, n: int) -> str:
    if lang == "pt-BR":
        return f"{n} ponto(s) de réplica rejeitado(s); envie os motivos de volta ao redator"
    return f"{n} rebuttal point(s) rejected; send their reasons back to the writer"
