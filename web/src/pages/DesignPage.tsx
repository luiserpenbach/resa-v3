import { useParams } from "wouter";
import { Section, useSession } from "../lib/session";
import { DesignWorkspace, SECTIONS } from "./DesignWorkspace";

export default function DesignPage() {
  const { pid, did, section } = useParams<{ pid: string; did: string; section?: string }>();
  const projectName = useSession((s) => s.projectName);
  const name = useSession((s) => s.meta?.name);
  const sec = (SECTIONS.find((s) => s.id === section)?.id ?? "performance") as Section;
  return (
    <DesignWorkspace
      source={{ kind: "project", pid, did }}
      section={sec}
      base={`/p/${pid}/d/${did}`}
      crumbs={[{ label: projectName || "Project", href: `/p/${pid}` }, { label: name ?? "…" }]}
    />
  );
}
