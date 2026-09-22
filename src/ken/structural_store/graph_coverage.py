"""Indexed CFG coverage shared across queries of one immutable graph."""


def coverage(index, general=False):
    cached = index._coverage.get(general)
    if cached is not None:
        return cached
    if general:
        from ken.kql2.source_coverage import supports_general_walk

        universe, base, _ = coverage(index)
        covered = set(base)
        for fact in index.rows("CFG_STATUS", object="partial"):
            owner = fact.subject
            if (
                owner not in covered
                and owner in index.ir.entities
                and index.rows("CFG_ENTRY", owner)
                and supports_general_walk([f for f in index.rows("CFG_STATUS", owner)])
            ):
                covered.add(owner)
    else:
        universe = {f.subject for f in index.rows("ENTITY", object="CALLABLE")}
        status, structured, entry = (
            index.term(t) for t in ("CFG_STATUS", "structured", "CFG_ENTRY")
        )
        covered = set()
        if None not in (status, structured, entry):
            covered = {
                row[0]
                for row in index.db.execute(
                    """
                SELECT DISTINCT t.text FROM k2_graph_facts f INDEXED BY k2_graph_fact_reverse
                JOIN k2_graph_terms t ON t.graph_id=f.graph_id AND t.term_id=f.subject
                WHERE f.graph_id=? AND f.relation=? AND f.object=?
                AND EXISTS (SELECT 1 FROM k2_graph_entities e WHERE e.graph_id=f.graph_id AND e.local_id=f.subject)
                AND EXISTS (SELECT 1 FROM k2_graph_facts e INDEXED BY k2_graph_fact_forward
                    WHERE e.graph_id=f.graph_id AND e.relation=? AND e.subject=f.subject)
                AND NOT EXISTS (SELECT 1 FROM k2_graph_facts s INDEXED BY k2_graph_fact_forward
                    WHERE s.graph_id=f.graph_id AND s.relation=? AND s.subject=f.subject AND s.object!=?)
                """,
                    (index.graph, status, structured, entry, status, structured),
                )
            }
    result = (universe, covered, universe - covered)
    index._coverage[general] = result
    return result
