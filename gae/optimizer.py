import torch
import torch.nn.modules.loss
import torch.nn.functional as F
import numpy as np


def loss_function(preds, labels, mu, logvar, n_nodes, norm, pos_weight):
    # todo: real labels should be 3D with types in 3rd dimension
    # todo which loss function
    labels = labels.unsqueeze(2).repeat(1, 1, 10)
    cost = norm * F.binary_cross_entropy_with_logits(preds, labels, pos_weight=torch.FloatTensor([pos_weight]))

    # see Appendix B from VAE paper:
    # Kingma and Welling. Auto-Encoding Variational Bayes. ICLR, 2014
    # https://arxiv.org/abs/1312.6114
    # 0.5 * sum(1 + log(sigma^2) - mu^2 - sigma^2)
    KLD = -0.5 / n_nodes * torch.mean(torch.sum(
        1 + 2 * logvar - mu.pow(2) - logvar.exp().pow(2), 1))
    return cost + KLD
