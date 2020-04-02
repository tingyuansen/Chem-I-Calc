from typing import Any, List, Tuple, Dict, Union, Optional, cast
import numpy as np
import pandas as pd
from chemicalc.reference_spectra import ReferenceSpectra, alpha_el
from chemicalc.instruments import InstConfig

def calc_crlb(
    reference: ReferenceSpectra,
    instruments: Union[InstConfig, List[InstConfig]],
    priors: Optional[Dict["str", float]] = None,
    use_alpha: bool = False,
    output_fisher: bool = False,
    chunk_size: int = 10000,
) -> Union[pd.DataFrame, Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    ToDo: Unit Tests
    Calculates the CRLB and FIM
    :param ReferenceSpectra reference: reference star object
    :param Union[InstConfig, List[InstConfig]] instruments: instrument object or list of instrument objects
    :param Optional[Dict['str', float]] priors: 1-sigma Gaussian priors for labels
    :param bool output_fisher: If true, outputs Fisher information matrix
    :param int chunk_size: Number of pixels to break spectra into. Helps with memory usage for large spectra.
    :return Union[pd.DataFrame, Tuple[pd.DataFrame, np.ndarray]]: DataFrame of CRLBs. If output_fisher=True, also returns FIM
    """
    if not isinstance(reference, ReferenceSpectra):
        raise TypeError("reference must be a chemicalc.reference_spectra.ReferenceSpectra object")
    if type(instruments) is not list:
        instruments = [instruments]
    grad_list = []
    snr_list = []
    for instrument in instruments:
        if not isinstance(instrument, InstConfig):
            raise TypeError("instruments must be chemicalc.instruments.InstConfig objects")
        if instrument.name not in reference.gradients.keys():
            raise KeyError(f"Reference star does not have gradients for {instrument.name}")
        grad_backup = reference.gradients[instrument.name].copy()
        if use_alpha and "alpha" not in reference.labels.index:
            raise ValueError("alpha not included in reference file")
        elif use_alpha:
            reference.zero_gradients(name=instrument.name, labels=alpha_el)
        elif not use_alpha and "alpha" in reference.labels.index:
            reference.zero_gradients(name=instrument.name, labels=["alpha"])
        grad_list.append(reference.gradients[instrument.name].values)
        snr_list.append(instrument.snr)
        reference.gradients[instrument.name] = grad_backup
    grad = np.concatenate(grad_list, axis=1)
    snr2 = np.concatenate(snr_list, axis=0) ** 2

    if chunk_size is not None:
        n_chunks = int(np.ceil(grad.shape[1] / chunk_size))
        fisher_mat = np.zeros((grad.shape[0], grad.shape[0]))
        for i in range(n_chunks):
            grad_tmp = grad[:, i * chunk_size : (i + 1) * chunk_size]
            snr2_tmp = np.diag(snr2[i * chunk_size : (i + 1) * chunk_size])
            fisher_mat += (grad_tmp.dot(snr2_tmp)).dot(grad_tmp.T)
    else:
        fisher_mat = (grad.dot(np.diag(snr2))).dot(grad.T)
    diag_val = np.abs(np.diag(fisher_mat)) < 1.0
    fisher_mat[diag_val, :] = 0.0
    fisher_mat[:, diag_val] = 0.0
    fisher_mat[diag_val, diag_val] = 10.0 ** -6
    fisher_df = pd.DataFrame(
        fisher_mat, columns=reference.labels.index, index=reference.labels.index
    )

    if not isinstance(priors, (None, dict)):
        raise TypeError("priors must be None or a dictionary of {label: prior}")
    if priors:
        for label in priors:
            prior = priors[label]
            if not isinstance(prior, (None, (int, float))):
                raise TypeError("prior dict entries must be None, int, or float")
            if label not in reference.labels.index:
                raise KeyError(f"{label} is not included in reference")
            if prior is None:
                continue
            if label == "Teff":
                prior /= 100
            if prior == 0:
                fisher_df.loc[label, :] = 0
                fisher_df.loc[:, label] = 0
                fisher_df.loc[label, label] = 1e-6
            else:
                fisher_df.loc[label, label] += prior ** (-2)

    crlb = pd.DataFrame(
        np.sqrt(np.diag(np.linalg.pinv(fisher_df))), index=reference.labels.index
    )

    if output_fisher:
        return crlb, fisher_df
    else:
        return crlb


def sort_crlb(crlb: pd.DataFrame, cutoff: float, sort_by: str = "default") -> pd.DataFrame:
    """
    ToDo: Unit Tests
    ToDo: Catch TypeErrors
    Sorts CRLB dataframe by decreasing precision of labels and removes labels with precisions worse than cutoff.
    :param pd.DataFrame crlb: dataframe of CRLBs
    :param float cutoff: Cutoff precision of labels
    :param str sort_by: Name of dataframe column to sort labels by. Default uses the column with the most labels below the cutoff
    :return pd.DataFrame: Sorted CRLB dataframe
    """
    crlb_temp = crlb[:3].copy()
    crlb[crlb > cutoff] = np.NaN
    crlb[:3] = crlb_temp

    if sort_by == "default":
        sort_by_index = np.sum(pd.isna(crlb)).idxmin()
    else:
        if sort_by == list(crlb.columns):
            sort_by_index = sort_by
        else:
            assert False, f"{sort_by} not in CR_Gradients_File"

    valid_ele = np.concatenate(
        [crlb.index[:3], crlb.index[3:][np.min(crlb[3:], axis=1) < cutoff]]
    )
    valid_ele_sorted = np.concatenate(
        [crlb.index[:3], crlb.loc[valid_ele][3:].sort_values(sort_by_index).index]
    )

    crlb = crlb.loc[valid_ele_sorted]
    return crlb