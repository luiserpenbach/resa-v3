import { createContext, useContext } from "react";

/** Base URL of the open design workspace (/estimate or /p/<pid>/d/<did>). */
export const BaseContext = createContext("/estimate");
export const useBase = () => useContext(BaseContext);
