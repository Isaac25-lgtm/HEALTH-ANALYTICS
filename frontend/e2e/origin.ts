/** The web origin of this run: the project contract (3000) unless the gate was given a spare port. */
export const WEB_ORIGIN = `http://localhost:${process.env.E2E_WEB_PORT ?? "3000"}`;
