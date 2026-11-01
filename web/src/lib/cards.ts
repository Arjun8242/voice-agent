// Card payloads sent by the server in `ui_card` messages (built by backend/tools/*.py).
// The card_id is stable (e.g. "link:github"), so a card sent twice replaces itself.

export type ProjectDetailCard = {
  card_id: string;
  type: 'project_detail';
  data: {
    project_id: string;
    name: string;
    status: string;
    section: string;
    text: string;
    links: { repo: string; live: string | null; video: string | null };
  };
};

export type LinkCard = {
  card_id: string;
  type: 'link';
  data: { label: string; url: string; description: string };
};

export type Card = ProjectDetailCard | LinkCard;
